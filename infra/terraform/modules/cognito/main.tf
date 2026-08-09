variable "env"            { type = string }
variable "callback_urls" { type = list(string) }

resource "aws_cognito_user_pool" "main" {
  name = "smart-${var.env}"

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  mfa_configuration = var.env == "prod" ? "ON" : "OPTIONAL"

  schema {
    name                     = "tenant_id"
    attribute_data_type      = "String"
    mutable                  = false
    required                 = false
    string_attribute_constraints {
      min_length = "36"
      max_length = "36"
    }
  }

  schema {
    name                     = "role"
    attribute_data_type      = "String"
    mutable                  = true
    required                 = false
    string_attribute_constraints {
      min_length = "1"
      max_length = "10"
    }
  }
}

resource "aws_cognito_user_pool_client" "main" {
  name                                 = "smart-${var.env}-web"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  callback_urls                        = var.callback_urls
  supported_identity_providers         = ["COGNITO"]
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
}

output "user_pool_id"     { value = aws_cognito_user_pool.main.id }
output "user_pool_arn"    { value = aws_cognito_user_pool.main.arn }
output "client_id"        { value = aws_cognito_user_pool_client.main.id }
