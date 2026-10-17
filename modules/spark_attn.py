# Copyright (C) 2026 CALMDUST / AiHUB
# SPDX-License-Identifier: Apache-2.0
"""spark_attn — 高速化「Spark（画質優先）」「Fast Spark（バランス）」。MiniMax H3 WebUI の拡張モジュール

Spark-H3（github.com/zechengtang/Spark-H3、Apache-2.0。同梱の sol_attn は FlashAttention 由来の部分が BSD-3-Clause、
cuDNN Frontend 由来の部分が Apache-2.0）を**版を固定して**取り寄せ、import して使う（コードは写さない）。
初めて Spark を選んだ生成で、取り寄せと依存（nvidia-cutlass-dsl・cuda-python・apache-tvm-ffi）の pip を行う。

本体（セル3）は `module_service("spark_ctx")` で下の `spark_ctx(mode)` を呼び、生成をその with の中で回す。
  mode = "spark"      … 最初の 1 回だけ密、以後は密度 10%（WebUI ver1.7 セル165: 768p で D との PSNR 18dB）
  mode = "fast_spark" … 密の回なし、最初の 1 回だけ密度 20%、以後 10%（同 15dB、Spark より約 7% 速い）
1 層目は常に密（Spark の既定）。短い列（8192 トークン未満＝静止画など）は Spark 自身が密で回す。
Spark の計算で例外が出たら、その生成の残りは元の処理器（密）で続ける（生成は止めない）。

もう 1 つの役目: Triton の組み立て結果（~/.triton/cache）を Google ドライブに控える（WebUI ver1.7 セル166:
新しい寸法の初回の待ち約 17 秒のうち約 16 秒が Triton の JIT、1 寸法で約 20MB）。起動時に Drive → ローカルへ戻し、
生成のたびに新しくできた分だけ Drive へ写す（`accel_sync`）。Drive と連携していなければ何もしない。
1.0.1: 使った控え（Triton が読んだ・書いたもの）は Drive 側の日付を新しくする＝上限を超えたら**使われていない順**に消す。
"""
import contextlib
import dataclasses
import importlib
import os
import shutil
import site
import subprocess
import sys
import threading

NAME = "spark_attn"
VERSION = "1.0.1"
API = 1
SLOTS = ()
CSS = ""

SPARK_REPO = "https://github.com/zechengtang/Spark-H3"
SPARK_COMMIT = "f58ecced3ff45fb32673839578fc9d19d78fdad8"      # 2026-10-16。版を固定する
SPARK_SRC = "/content/_spark_src"
SPARK_PIP = (("cutlass", "nvidia-cutlass-dsl>=4.4"), ("cuda.bindings", "cuda-python>=12"), ("tvm_ffi", "apache-tvm-ffi"))
TOPK = 0.10                 # 以後の密度
EARLY_TOPK = 0.20           # Fast Spark の最初の 1 回
MAX_EVALS = 100000          # Spark の「回数の上限」。歩数は Express・σ裾などで変わるので数えず、大きく取る
TRITON_DRIVE_SUB = "triton_cache"
TRITON_DRIVE_CAP_MB = 500   # Drive の控えの上限（超えたら**最後に使った日が古いもの**から消す＝1.0.1）

I18N = {
    "⚙️ Spark を準備しています（初回だけ 1 分ほどかかります）": {"en": "⚙️ Preparing Spark (first time only, about a minute)", "zh": "⚙️ 正在准备 Spark（仅首次，约 1 分钟）", "ko": "⚙️ Spark를 준비하고 있습니다(처음 한 번만, 1분 정도)"},
    "⚠️ Spark を使えないので SLA で生成します: {v0}": {"en": "⚠️ Spark is unavailable, generating with SLA instead: {v0}", "zh": "⚠️ 无法使用 Spark，改用 SLA 生成：{v0}", "ko": "⚠️ Spark를 사용할 수 없어 SLA로 생성합니다: {v0}"},
    "⚠️ Spark の計算で失敗したので、この生成の残りは密で回しました: {v0}": {"en": "⚠️ Spark failed, so the rest of this generation ran dense: {v0}", "zh": "⚠️ Spark 计算失败，本次生成的剩余部分改为密集计算：{v0}", "ko": "⚠️ Spark 계산에 실패해 이번 생성의 나머지는 밀집으로 처리했습니다: {v0}"},
    "⚡ {v0}: 疎 {v1} / 密 {v2}": {"en": "⚡ {v0}: sparse {v1} / dense {v2}", "zh": "⚡ {v0}：稀疏 {v1} / 密集 {v2}", "ko": "⚡ {v0}: 희소 {v1} / 밀집 {v2}"},
    "ℹ️ この寸法では初めて使う部品を組み立てたので、そのぶん長くかかりました（次回からは Drive の控えを使います）": {"en": "ℹ️ Kernels for this size were built for the first time, which added some time (next time the copy on Drive is used)", "zh": "ℹ️ 首次为此尺寸构建计算组件，因此耗时更长（下次将使用 Drive 上的缓存）", "ko": "ℹ️ 이 크기에서 처음 쓰는 부품을 조립해 그만큼 오래 걸렸습니다(다음부터는 Drive의 사본을 씁니다)"},
    "ℹ️ この寸法では初めて使う部品を組み立てたので、そのぶん長くかかりました（Drive と連携していないので、控えはこのセッションの間だけ）": {"en": "ℹ️ Kernels for this size were built for the first time, which added some time (Drive is not connected, so they are kept for this session only)", "zh": "ℹ️ 首次为此尺寸构建计算组件，因此耗时更长（未连接 Drive，缓存仅在本次会话中有效）", "ko": "ℹ️ 이 크기에서 처음 쓰는 부품을 조립해 그만큼 오래 걸렸습니다(Drive와 연동되지 않아 이번 세션 동안만 유지)"},
}

_CTX = {"g": None}
_ST = {"hsa": None, "err": "", "lock": threading.Lock(), "sync": None, "track": False}
_USED = set()               # このセッションで Triton が読んだ・書いた控えの鍵（＝フォルダ名）


def _g():
    return _CTX["g"]


def _T(s, **kw):
    return _g()["T"](s, **kw)


def _log(s):
    _g()["log"](s)


# ------------------------------------------------------------------
#  Triton の控え（Drive）
# ------------------------------------------------------------------
def _triton_local():
    return os.environ.get("TRITON_CACHE_DIR") or os.path.expanduser("~/.triton/cache")


def _triton_drive():
    """Drive の控えの置き場。Drive と連携していなければ None（その場合は何もしない）"""
    cd = str(_g().get("CACHE_DIR") or "")
    if not cd.startswith("/content/drive/") or not os.path.isdir(cd):
        return None
    return os.path.join(cd, TRITON_DRIVE_SUB)


def _copy_entries(src, dst, since=None):
    """src の直下のフォルダ（Triton の 1 件）を dst へ写す。dst に既にあるものは飛ばす → 写した件数"""
    n = 0
    if not os.path.isdir(src):
        return 0
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        try:
            if not os.path.isdir(s) or os.path.exists(d):
                continue
            if since is not None and os.path.getmtime(s) < since:
                continue
            tmp = d + ".part"
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.copytree(s, tmp)
            os.replace(tmp, d)
            n += 1
        except Exception:                                        # noqa: BLE001
            continue
    return n


def _prune(dst, cap_mb):
    try:
        ents = []
        for name in os.listdir(dst):
            p = os.path.join(dst, name)
            if os.path.isdir(p) and not name.endswith(".part"):
                sz = sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(p) for f in fs)
                ents.append((os.path.getmtime(p), sz, p))
        tot = sum(e[1] for e in ents)
        for _t, sz, p in sorted(ents):
            if tot <= cap_mb * 1e6:
                break
            shutil.rmtree(p, ignore_errors=True)
            tot -= sz
    except Exception:                                            # noqa: BLE001
        pass


def triton_restore():
    """起動時（setup）に裏で 1 回: Drive の控え → ローカルの Triton の置き場"""
    drv = _triton_drive()
    if not drv or not os.path.isdir(drv):
        return
    threading.Thread(target=_copy_entries, args=(drv, _triton_local()), daemon=True).start()


def _track_triton():
    """Triton の控えの読み書きを数える（1.0.1）。使った控えは Drive 側の日付を新しくし、消すのは使われていないものから。
    Triton の FileCacheManager の get_file / get_group / put / put_group を包むだけ（中身は変えない・冪等）"""
    if _ST["track"]:
        return
    try:
        from triton.runtime import cache as _tc
        cls = _tc.FileCacheManager
        for nm in ("get_file", "get_group", "put", "put_group"):
            f = getattr(cls, nm, None)
            if f is None or getattr(f, "_h3_track", False):
                continue

            def _wrap(fn):
                def w(self, *a, **kw):
                    r = fn(self, *a, **kw)
                    try:
                        if r is not None and getattr(self, "key", None):
                            _USED.add(str(self.key))
                    except Exception:                            # noqa: BLE001
                        pass
                    return r
                w._h3_track = True
                return w
            setattr(cls, nm, _wrap(f))
        _ST["track"] = True
    except Exception:                                            # noqa: BLE001
        pass                                                     # 数えられなくても動作は変わらない（作った順で消えるだけ）


def _touch_used(drv):
    """このセッションで使った控えの Drive 側の日付を今にする → 戻り値は日付を直した件数"""
    n = 0
    for key in list(_USED):
        d = os.path.join(drv, key)
        try:
            if os.path.isdir(d):
                os.utime(d, None)
                n += 1
        except OSError:
            pass
    _USED.clear()
    return n


def _new_local_entries(since):
    loc = _triton_local()
    if not os.path.isdir(loc):
        return 0
    n = 0
    for name in os.listdir(loc):
        try:
            if os.path.getmtime(os.path.join(loc, name)) >= since:
                n += 1
        except OSError:
            pass
    return n


def accel_sync(t0):
    """生成のあと（本体が毎回呼ぶ）: t0 以降に新しくできた Triton の組み立て結果を Drive へ写す（裏で）。
    → 新しくできた件数（0 なら、この寸法の部品は既にそろっていた）"""
    n = _new_local_entries(t0)
    drv = _triton_drive()
    if drv and (n or _USED):
        def _job():
            if n:
                _copy_entries(_triton_local(), drv, since=t0)
            _touch_used(drv)                                     # 使ったものを新しく → 消すのは使われていないものから
            _prune(drv, TRITON_DRIVE_CAP_MB)
        th = threading.Thread(target=_job, daemon=True)
        th.start()
        _ST["sync"] = th
    return n


# ------------------------------------------------------------------
#  Spark の用意（版固定の取り寄せ・依存・import）
# ------------------------------------------------------------------
def _prepare():
    """→ h3_sparse_attention モジュール。失敗は例外（理由つき）"""
    with _ST["lock"]:
        if _ST["hsa"] is not None:
            return _ST["hsa"]
        _log(_T("⚙️ Spark を準備しています（初回だけ 1 分ほどかかります）"))
        if not os.path.isdir(os.path.join(SPARK_SRC, ".git")):
            subprocess.run(["git", "clone", "-q", SPARK_REPO, SPARK_SRC], check=True)
        subprocess.run(["git", "-C", SPARK_SRC, "fetch", "-q", "--all"], check=False)
        subprocess.run(["git", "-C", SPARK_SRC, "checkout", "-q", SPARK_COMMIT], check=True)
        need = []
        for mod, spec in SPARK_PIP:
            try:
                importlib.import_module(mod)
            except Exception:                                    # noqa: BLE001
                need.append(spec)
        if need:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *need], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"pip: {(r.stderr or r.stdout)[-300:]}")
        # nvidia-cutlass-dsl は .pth で path を足す作り。.pth は起動時にしか読まれないので読み直す
        for d in list(site.getsitepackages()) + [site.getusersitepackages()]:
            if os.path.isdir(d):
                site.addsitedir(d)
        importlib.invalidate_caches()
        importlib.import_module("cutlass.cute")
        if SPARK_SRC not in sys.path:
            sys.path.insert(0, SPARK_SRC)
        sys.path_importer_cache.pop(SPARK_SRC, None)
        importlib.invalidate_caches()
        hsa = importlib.import_module("h3_sparse_attention")
        _ST["hsa"] = hsa
        return hsa


class _SafeProc:
    """Spark の処理器を包む。例外が出たらこの生成の残りは元の処理器（密）へ"""

    def __init__(self, sparse, orig, state):
        self.sparse, self.orig, self.state = sparse, orig, state

    def __call__(self, attn, hidden_states, rotary_emb=None, attention_mask=None):
        if not self.state["dead"]:
            try:
                return self.sparse(attn, hidden_states, rotary_emb, attention_mask)
            except Exception as e:                               # noqa: BLE001
                self.state["dead"] = True
                self.state["err"] = f"{type(e).__name__}: {str(e)[:160]}"
        return self.orig(attn, hidden_states, rotary_emb, attention_mask)


@contextlib.contextmanager
def spark_ctx(mode):
    """生成をこの with の中で回す。→ box: ok（Spark が張れたか）・err・note（STATUS に足す行）"""
    box = {"ok": False, "err": "", "note": "", "mode": mode}
    try:
        hsa = _prepare()
        _track_triton()
        tr = _g()["active_transformer"]()
    except Exception as e:                                       # noqa: BLE001
        box["err"] = f"{type(e).__name__}: {str(e)[:200]}"
        _ST["err"] = box["err"]
        yield box
        return
    fast = (mode == "fast_spark")
    state = {"dead": False, "err": ""}
    cm = att = None
    try:
        cm = hsa.install_h3_spark_attn(tr, num_denoise_steps=MAX_EVALS, warmup_mode="warmup_steps",
                                       warmup_steps=0 if fast else 1, topk_ratio=TOPK)
        att = cm.__enter__()
        ctl = att.controller
        base_cfg = ctl.config
        early_cfg = dataclasses.replace(base_cfg, sol_route_topk_ratio=EARLY_TOPK) if fast else None
        for attn, orig in list(att._originals):
            attn.set_processor(_SafeProc(attn.get_processor(), orig, state))
        # 呼び出しの数え上げ（Spark の前フック）を包み直す: 失敗しても生成を止めない＋Fast Spark の密度の切り替え
        if att._hook is not None:
            att._hook.remove()

        def _begin(m, a, kw):
            try:
                ctl.begin_forward(m, a, kw)
            except Exception as e:                               # noqa: BLE001
                state["dead"] = True
                state["err"] = state["err"] or f"{type(e).__name__}: {str(e)[:160]}"
            if early_cfg is not None:
                ctl.config = early_cfg if ctl.evaluation_index < 1 else base_cfg
        att._hook = tr.register_forward_pre_hook(_begin, with_kwargs=True)
        box["ok"] = True
    except Exception as e:                                       # noqa: BLE001
        box["err"] = f"{type(e).__name__}: {str(e)[:200]}"
        if cm is not None and att is not None:
            try:
                cm.__exit__(None, None, None)            # 張りかけた処理器を元に戻してから、Spark なしで回す
            except Exception:                                    # noqa: BLE001
                pass
        yield box
        return
    try:
        yield box
    finally:
        try:
            ctl.config = base_cfg
            calls = dict((att.summary() or {}).get("processor_calls") or {})
            sp = sum(int(v) for k, v in calls.items() if str(k).startswith("sparse"))
            dn = sum(int(v) for k, v in calls.items() if str(k).startswith("dense"))
            label = "Fast Spark" if fast else "Spark"
            box["note"] = _T("⚡ {v0}: 疎 {v1} / 密 {v2}", v0=label, v1=f"{sp}", v2=f"{dn}")
            if state["dead"]:
                box["note"] += "\n" + _T("⚠️ Spark の計算で失敗したので、この生成の残りは密で回しました: {v0}",
                                          v0=state["err"])
        except Exception:                                        # noqa: BLE001
            pass
        try:
            cm.__exit__(None, None, None)
        except Exception:                                        # noqa: BLE001
            pass


def first_build_note(n_new):
    """本体が accel_sync の件数を渡す → 初回の組み立てがあったときの STATUS の行（無ければ空）"""
    if not n_new:
        return ""
    if _triton_drive():
        return _T("ℹ️ この寸法では初めて使う部品を組み立てたので、そのぶん長くかかりました（次回からは Drive の控えを使います）")
    return _T("ℹ️ この寸法では初めて使う部品を組み立てたので、そのぶん長くかかりました（Drive と連携していないので、控えはこのセッションの間だけ）")


def setup(ctx):
    _CTX["g"] = ctx.g
    ctx.provide("spark_ctx", spark_ctx)
    ctx.provide("accel_sync", accel_sync)
    ctx.provide("accel_first_note", first_build_note)
    try:
        triton_restore()
    except Exception:                                            # noqa: BLE001
        pass


def build_slot(ctx, slot):
    return None


def wire(ctx, comps):
    return None
