# Recorded runs

Verbatim output from the proof scripts, committed so a reader can compare what they get
against what we got rather than take the numbers on trust.

| file | produced by | needs |
|---|---|---|
| `collapse.txt` | `scripts/verify_collapse.py` | nothing |
| `ablation.txt` | `scripts/ablation.py` | nothing |
| `determinism.txt` | `scripts/verify_determinism.py` | nothing |
| `swarm-20000.txt` | `scripts/prove_swarm.py --agents 20000` | Vertex AI credentials · ~$0.21 · ~6 min |

The first three are deterministic and should reproduce exactly. The fourth calls a live
model, so token counts and wall clock will differ; the collapse ratio should not.
