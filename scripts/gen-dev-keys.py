"""Generate Ed25519 dev keypairs for Beckn signing.

Writes raw base64 private + public key files to <out_dir>/<name>.private.b64
and <name>.public.b64. These are TEXT files containing the base64 ed25519
seed / public key — easier to ship around than PEM.

Usage:
    python scripts/gen-dev-keys.py dev/keys seller safiyafood antarestar gendes yourbrand

These keys are FOR DEVELOPMENT ONLY. Never use in production.
"""

import base64
import sys
from pathlib import Path

from nacl.signing import SigningKey


def gen(out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sk = SigningKey.generate()
    priv_b64 = base64.b64encode(bytes(sk)).decode()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    (out_dir / f"{name}.private.b64").write_text(priv_b64 + "\n")
    (out_dir / f"{name}.public.b64").write_text(pub_b64 + "\n")
    print(f"  {name}: pub={pub_b64[:20]}...")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: gen-dev-keys.py <out_dir> <name1> [<name2> ...]")
        sys.exit(1)
    out_dir = Path(sys.argv[1])
    names = sys.argv[2:]
    print(f"writing {len(names)} keypairs to {out_dir}/")
    for n in names:
        gen(out_dir, n)
    print("done. NEVER use these in production.")


if __name__ == "__main__":
    main()
