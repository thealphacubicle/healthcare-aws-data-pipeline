terraform {
  # Values are intentionally left out so the same config works for any
  # account/region. Supply them with -backend-config=backend.hcl (copy from
  # backend.hcl.example, filled in from `infra/bootstrap` outputs), or with
  # -backend-config flags, as the CI deploy workflow does.
  backend "s3" {}
}
