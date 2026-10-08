# Archived — Cognito Terraform module

**Why archived:** SMART owns login itself (Option B) — `POST /api/v1/auth/token`
in `backend/services/auth-service` issues and verifies the platform's own
JWTs; see commits `68b3cf8` and `4d6dcd9`. AWS Cognito is not used at launch.
This module is kept, unwired, for a possible future SSO integration — it is
not deleted so the original dev/stage/prod wiring doesn't have to be
reconstructed from scratch if that need arises.

## Env blocks removed (copied verbatim before removal)

### envs/dev/main.tf

```hcl
module "cognito" {
  source         = "../../modules/cognito"
  env            = "dev"
  callback_urls  = ["https://app.dev.smart-platform.com/auth/callback"]
}
```

### envs/stage/main.tf

```hcl
module "cognito" {
  source        = "../../modules/cognito"
  env           = "stage"
  callback_urls = ["https://app.stage.smart-platform.com/auth/callback"]
}
```

### envs/prod/main.tf

```hcl
module "cognito" {
  source        = "../../modules/cognito"
  env           = "prod"
  callback_urls = ["https://app.smart-platform.com/auth/callback"]
}
```

## Restore steps

1. `git mv infra/terraform/_archived/cognito infra/terraform/modules/cognito`
2. Re-add the removed `module "cognito" { ... }` block (above, per env) back
   into `infra/terraform/envs/dev/main.tf`, `envs/stage/main.tf`, and
   `envs/prod/main.tf`, in the same position relative to the other modules.
3. Remove this README (or move it back into a non-archived location) and
   re-run `terraform init` / `terraform plan` for each env.
