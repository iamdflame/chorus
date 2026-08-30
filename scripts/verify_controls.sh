#!/usr/bin/env bash
# Prove the tool allowlist is enforced by IAM rather than by a prompt.
#
# A README paragraph claiming least privilege is worth nothing. This attempts the
# forbidden action from each agent's own identity and reports the denial, and — the part
# that makes it a real check — it also attempts actions that are *supposed* to succeed.
# An identity that can do nothing proves only that it is broken, so a run where every
# probe is denied FAILS here rather than looking maximally secure.
#
#   ./scripts/verify_controls.sh
#
# Requires the identities from infra/identity.sh and permission to impersonate them.

set -uo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
LOCATION="${VERTEX_LOCATION:-global}"
MODEL="${CHORUS_MODEL:-gemini-3.5-flash}"

if [[ -z "$PROJECT" ]]; then
  echo "  GOOGLE_CLOUD_PROJECT is unset and gcloud has no default project." >&2
  exit 1
fi

pass=0; fail=0

sa() { echo "chorus-$1@${PROJECT}.iam.gserviceaccount.com"; }

# Run a probe as one agent identity. Prints one line and records pass/fail.
#   probe <role> <expected: ALLOW|DENY> <label> <command...>
probe() {
  local role="$1" expected="$2" label="$3"; shift 3
  local token out status
  token=$(gcloud auth print-access-token --impersonate-service-account="$(sa "$role")" 2>/dev/null)
  if [[ -z "$token" ]]; then
    printf "  %-11s %-6s %-42s %s\n" "$role" "$expected" "$label" "SKIP (cannot impersonate)"
    return
  fi
  out=$("$@" "$token" 2>&1); status=$?
  local got="ALLOW"
  if [[ $status -ne 0 ]] || grep -qiE "permission|denied|forbidden|403|unauthorized" <<<"$out"; then
    got="DENY"
  fi
  if [[ "$got" == "$expected" ]]; then
    printf "  %-11s %-6s %-42s \033[32m%s\033[0m\n" "$role" "$expected" "$label" "OK ($got)"
    pass=$((pass+1))
  else
    printf "  %-11s %-6s %-42s \033[31m%s\033[0m\n" "$role" "$expected" "$label" "WRONG ($got)"
    fail=$((fail+1))
  fi
}

call_model() {
  local token="$1"
  curl -sS -o /dev/null -w "%{http_code}" --max-time 30 \
    -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
    "https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${LOCATION}/publishers/google/models/${MODEL}:generateContent" \
    -d '{"contents":[{"role":"user","parts":[{"text":"ping"}]}]}' \
  | grep -qE "^2" || { echo "denied"; return 1; }
}

read_firestore() {
  local token="$1"
  curl -sS --max-time 30 -H "Authorization: Bearer $token" \
    "https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/(default)/documents/effects?pageSize=1" \
  | grep -qi "error" && { echo "denied"; return 1; }
}

write_firestore() {
  local token="$1"
  curl -sS --max-time 30 -X POST -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    "https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/(default)/documents/controlcheck" \
    -d '{"fields":{"probe":{"stringValue":"verify_controls"}}}' \
  | grep -qi "error" && { echo "denied"; return 1; }
}

echo
echo "  Tool allowlist, enforced by IAM — project ${PROJECT}"
echo
printf "  %-11s %-6s %-42s %s\n" "identity" "expect" "action" "result"
printf "  %s\n" "-------------------------------------------------------------------------------"

# Expected ALLOWED. Without these the run would prove only that the identities are broken.
probe extractor ALLOW "call Gemini (its entire job)"            call_model
probe elicitor  ALLOW "call Gemini (its entire job)"            call_model

# Expected DENIED. The allocator is deterministic by design; a model there would be both
# dearer and worse, so it is not merely unused — it is unreachable.
probe allocator DENY  "call Gemini (allocation needs no model)" call_model
probe extractor DENY  "write to Firestore (it only reads)"      write_firestore
probe elicitor  DENY  "write to Firestore (it only reads)"      write_firestore

echo
if [[ $fail -gt 0 ]]; then
  echo "  FAIL  ${fail} control(s) did not behave as declared, ${pass} did."
  echo
  exit 1
fi
if [[ $pass -eq 0 ]]; then
  echo "  SKIP  no identity could be impersonated; nothing was proved."
  echo "        Run infra/identity.sh first, and grant yourself"
  echo "        roles/iam.serviceAccountTokenCreator on these accounts."
  echo
  exit 1
fi
echo "  PASS  ${pass} controls behaved exactly as declared."
echo "        Two of them are ALLOW — an identity that can do nothing proves nothing."
echo
