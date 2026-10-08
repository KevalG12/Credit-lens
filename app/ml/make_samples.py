"""Write three demo statements to data/.   Run:  python -m app.ml.make_samples"""
from pathlib import Path

import numpy as np

from app.ml.synthetic import Profile, generate_statement

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

PERSONAS = {
    # salaried intern: pays on time, steady income, saves
    "steady_intern": (11, Profile(0.92, 0.95, 32000, 12, 0.22, 0.0, 0.30, True, 0.08)),
    # gig driver: income arrives in uneven chunks, but pays bills mostly on time and saves a little
    "gig_driver": (12, Profile(0.75, 0.40, 24000, 9, 0.30, 0.05, 0.40, True, 0.25)),
    # stretched student: heavy rent and EMI, late payments, little history
    "stretched_student": (13, Profile(0.20, 0.55, 18000, 6, 0.45, 0.20, 0.60, False, 0.50)),
}


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for name, (seed, profile) in PERSONAS.items():
        df = generate_statement(np.random.default_rng(seed), profile)
        df.to_csv(DATA_DIR / f"{name}.csv", index=False)
        print(f"wrote data/{name}.csv ({len(df)} rows)")


if __name__ == "__main__":
    main()
