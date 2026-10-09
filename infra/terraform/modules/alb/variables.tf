variable "env" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "certificate_arn" {
  type    = string
  default = ""
}
variable "idle_timeout" {
  type    = number
  default = 60
}
variable "allowed_cidrs" { type = list(string) }
