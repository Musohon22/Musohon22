"""Measure face-matching accuracy on your own labelled photos before trusting any threshold.

    python scripts/evaluate_biometrics.py --data DIR [--impostors DIR] [--provider onnx --detector det.onnx
        --recognizer rec.onnx] [--enroll 3] [--out report]

Dataset layout (one folder per person, any JPG/PNG names):

    DIR/<person>/*.jpg         first --enroll images build the template, the rest are probes
    IMPOSTORS/<person>/*.jpg   optional: people who are NOT enrolled (open-set test — the
                               realistic case of a visitor or a new hire walking up to the gate)

Templates and scores are computed exactly like production (mean of L2-normalised embeddings,
cosine similarity, best match against the whole gallery). The report gives FAR/FRR per threshold
with 95% confidence intervals, EER, rank-1 identification, failure-to-acquire, and threshold
suggestions — and says plainly when the sample is too small to support a claim. Liveness / PAD
is not evaluated here: attack testing needs real presentation attacks (prints, screens, masks).

The DEV provider is not a face recognizer; running this with it only exercises the pipeline.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fras.biometrics import imaging  # noqa: E402
from fras.biometrics.providers import DevProvider, OnnxProvider, Provider  # noqa: E402

EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion k/n (honest at small n and at 0 errors)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load_people(root: Path) -> dict[str, list[Path]]:
    people = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(f for f in d.iterdir() if f.suffix.lower() in EXT)
        if files:
            people[d.name] = files
    return people


def embed_file(provider: Provider, path: Path) -> np.ndarray | None:
    """None = failure to acquire (no face, or more than one face)."""
    img = imaging.decode(path.read_bytes())
    faces = provider.detect(img)
    if len(faces) != 1:
        return None
    v = provider.embed(img, faces[0]).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def evaluate(provider: Provider, data: Path, impostors: Path | None, n_enroll: int) -> dict:
    people = load_people(data)
    if len(people) < 2:
        raise SystemExit("need at least 2 people in --data")
    t0 = time.time()
    attempts = fta = 0
    gallery_ids, gallery = [], []
    probes: list[tuple[str, np.ndarray]] = []
    skipped = []
    for pid, files in people.items():
        if len(files) <= n_enroll:
            skipped.append(pid)
            continue
        vecs = []
        for f in files[:n_enroll]:
            v = embed_file(provider, f)
            attempts += 1
            if v is None:
                fta += 1
            else:
                vecs.append(v)
        if not vecs:
            skipped.append(pid)
            continue
        m = np.mean(np.stack(vecs), axis=0)
        gallery_ids.append(pid)
        gallery.append(m / (np.linalg.norm(m) + 1e-9))
        for f in files[n_enroll:]:
            v = embed_file(provider, f)
            attempts += 1
            if v is None:
                fta += 1
            else:
                probes.append((pid, v))
    G = np.stack(gallery)
    genuine, impostor_best, rank1_ok = [], [], 0
    for pid, v in probes:
        s = G @ v
        own = gallery_ids.index(pid)
        genuine.append(float(s[own]))
        others = np.delete(s, own)
        impostor_best.append(float(others.max()))   # strongest wrong candidate = what could open the gate
        rank1_ok += int(int(np.argmax(s)) == own)
    open_set = []
    if impostors:
        for pid, files in load_people(impostors).items():
            if pid in gallery_ids:
                continue
            for f in files:
                v = embed_file(provider, f)
                attempts += 1
                if v is None:
                    fta += 1
                else:
                    open_set.append(float((G @ v).max()))
    return {"people_enrolled": len(gallery_ids), "people_skipped": skipped, "probes": len(probes),
            "open_set_probes": len(open_set), "attempts": attempts, "failure_to_acquire": fta,
            "genuine": genuine, "impostor_closed": impostor_best, "impostor_open": open_set,
            "rank1": rank1_ok, "seconds": round(time.time() - t0, 1)}


def rates(r: dict, t: float) -> dict:
    gen = np.array(r["genuine"])
    imp = np.array(r["impostor_closed"] + r["impostor_open"])
    fr = int((gen < t).sum())
    fa = int((imp >= t).sum())
    return {"threshold": round(t, 3), "frr": fr / max(1, len(gen)), "frr_ci": wilson(fr, len(gen)),
            "far": fa / max(1, len(imp)), "far_ci": wilson(fa, len(imp)), "false_rejects": fr, "false_accepts": fa}


def summarize(r: dict) -> dict:
    gen, imp = r["genuine"], r["impostor_closed"] + r["impostor_open"]
    grid = [round(x, 3) for x in np.arange(0.20, 0.951, 0.01)]
    table = [rates(r, t) for t in grid]
    eer = min(table, key=lambda x: abs(x["far"] - x["frr"]))
    n_imp = len(imp)
    # Smallest FAR this sample can support with zero observed errors ("rule of three", ~95%).
    far_floor = 3 / n_imp if n_imp else 1.0
    # accept: first threshold with no observed false accept, plus a 0.02 safety margin;
    # review: where ~99% of genuine scores still land, so most real people reach at least the border zone.
    zero_fa = next((x for x in table if x["false_accepts"] == 0), None)
    accept = rates(r, min(0.95, zero_fa["threshold"] + 0.02)) if zero_fa else None
    review = None
    if accept and gen:
        review = rates(r, max(0.2, min(accept["threshold"] - 0.05, math.floor(float(np.percentile(gen, 1)) * 100) / 100)))
    warnings = []
    if n_imp < 3000:
        warnings.append(f"Only {n_imp} impostor comparisons: the lowest FAR this sample can demonstrate is about "
                        f"{far_floor:.1e}. A gate claim of FAR ≤ 1e-4 needs ≥ 30 000 impostor comparisons with no false accept.")
    if len(gen) < 300:
        warnings.append(f"Only {len(gen)} genuine probes: FRR estimates are wide (see confidence intervals).")
    if not r["impostor_open"]:
        warnings.append("No --impostors set: open-set behaviour (people who are not enrolled) was not measured.")
    if r["people_skipped"]:
        warnings.append(f"Skipped {len(r['people_skipped'])} people with too few usable images.")
    return {"eer": eer, "table": table, "suggest_accept": accept, "suggest_review": review, "warnings": warnings,
            "rank1": r["rank1"] / max(1, r["probes"]), "fta_rate": r["failure_to_acquire"] / max(1, r["attempts"]),
            "genuine_pctl": np.percentile(gen, [1, 5, 50]).round(3).tolist() if gen else [],
            "impostor_pctl": np.percentile(imp, [50, 99, 99.9]).round(3).tolist() if imp else []}


def markdown(r: dict, s: dict, provider_name: str) -> str:
    pct = lambda x: f"{100 * x:.3f}%"  # noqa: E731
    ci = lambda c: f"[{pct(c[0])} – {pct(c[1])}]"  # noqa: E731
    lines = [f"# Biometric evaluation ({provider_name})", "",
             f"- Enrolled people: {r['people_enrolled']}; genuine probes: {r['probes']}; open-set probes: {r['open_set_probes']}",
             f"- Failure to acquire (0 or >1 faces): {pct(s['fta_rate'])} of {r['attempts']} images",
             f"- Rank-1 identification (closed set): {pct(s['rank1'])}",
             f"- EER ≈ {pct((s['eer']['far'] + s['eer']['frr']) / 2)} at threshold {s['eer']['threshold']}",
             f"- Genuine score percentiles p1/p5/p50: {s['genuine_pctl']}; impostor p50/p99/p99.9: {s['impostor_pctl']}", ""]
    if provider_name == "dev":
        lines += ["> **DEV provider: these numbers describe a test stand-in, not face recognition.**", ""]
    if s["warnings"]:
        lines += ["## Limits of this sample", *[f"- {w}" for w in s["warnings"]], ""]
    lines += ["## Suggested policy thresholds (verify in a pilot)",
              (f"- accept (gate opens): {s['suggest_accept']['threshold']} — FAR observed 0 (95% CI up to "
               f"{pct(s['suggest_accept']['far_ci'][1])}); {pct(s['suggest_accept']['frr'])} of genuine attempts fall below it"
               if s["suggest_accept"] else "- accept: none found — every threshold up to 0.95 had a false accept; do not deploy this model"),
              (f"- review (border zone starts): {s['suggest_review']['threshold']} — below it the attempt is \"unknown\"; "
               f"{pct(s['suggest_review']['frr'])} of genuine attempts fall below it" if s["suggest_review"] else "- review: n/a"),
              "- Scores between review and accept go to retry → card/PIN → HR review, never straight to a gate opening.", "",
              "## FAR / FRR by threshold", "", "| threshold | FAR | FAR 95% CI | FRR | FRR 95% CI |", "|---|---|---|---|---|"]
    for x in s["table"][::5]:
        lines.append(f"| {x['threshold']} | {pct(x['far'])} | {ci(x['far_ci'])} | {pct(x['frr'])} | {ci(x['frr_ci'])} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--impostors", type=Path)
    ap.add_argument("--provider", choices=["onnx", "dev"], default="onnx")
    ap.add_argument("--detector")
    ap.add_argument("--recognizer")
    ap.add_argument("--enroll", type=int, default=3, help="images per person used to build the template")
    ap.add_argument("--out", type=Path, default=Path("biometric-eval"), help="writes <out>.json and <out>.md")
    a = ap.parse_args(argv)
    if a.provider == "onnx":
        if not (a.detector and a.recognizer):
            ap.error("--detector and --recognizer ONNX files are required for --provider onnx")
        provider = OnnxProvider(a.detector, a.recognizer)
    else:
        provider = DevProvider()
    r = evaluate(provider, a.data, a.impostors, a.enroll)
    s = summarize(r)
    a.out.with_suffix(".json").write_text(json.dumps({"provider": a.provider, "summary": s,
                                                      **{k: v for k, v in r.items() if k not in ("genuine", "impostor_closed", "impostor_open")},
                                                      "scores": {"genuine": r["genuine"], "impostor_closed": r["impostor_closed"],
                                                                 "impostor_open": r["impostor_open"]}}, indent=1), encoding="utf-8")
    md = markdown(r, s, a.provider)
    a.out.with_suffix(".md").write_text(md, encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")   # Windows consoles may not have ≤/≈
    print(md)


if __name__ == "__main__":
    main()
