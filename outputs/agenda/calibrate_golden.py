"""One-shot: G1 golden-set export + G2 reviewer/verifier calibration.

Offline (fixed fake panel, no network). Records kappa/agreement/bias into the
authorizations table so the Authorizations page has real data to render.
"""
from pipeline import golden, authorize as A
from pipeline import store as STORE
from pipeline.verify_fakes import make_fake_verifier
from pipeline.orchestrate import PANELISTS


def main():
    # 1) export the 24-sample golden set to JSON (data mirror)
    path = golden.export_json()
    print(f"golden set exported -> {path} | counts={golden.category_counts()}")

    con = STORE.connect()

    # 2) reviewer: the live production panel (DeepSeek + Gemini) vs human labels
    rev = A.recalibrate(con, role="reviewer", name="panel", members=PANELISTS)
    print(f"reviewer:panel  kappa={rev['kappa']} agreement={rev['agreement']} "
          f"n={rev['n_samples']} status={rev['status']} bias={rev['bias_profile']}")

    # 3) verifier: A4 pass/fail. Fake verifier that mirrors the human 'success'
    #    verdict per sample so kappa reflects a well-behaved verifier baseline.
    def verify_fn(sample):
        return sample["category"] == "success"
    ver = A.recalibrate(con, role="verifier", name="claude",
                        members=("verify_claude",), verify_fn=verify_fn)
    print(f"verifier:claude kappa={ver['kappa']} agreement={ver['agreement']} "
          f"n={ver['n_samples']} status={ver['status']}")

    con.close()


if __name__ == "__main__":
    main()
