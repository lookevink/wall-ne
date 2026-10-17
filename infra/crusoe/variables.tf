variable "project_id" {
  type        = string
  description = "Crusoe infrastructure project UUID."
}
variable "name" {
  type    = string
  default = "wall-ne-nemotron-trainer"
}
variable "location" {
  type        = string
  description = "Zone with available GPU capacity; no implicit regional fallback."
}
variable "instance_type" {
  type        = string
  description = "GPU SKU from the current Crusoe inventory, e.g. a100-80gb.1x."
}
variable "image" {
  type        = string
  description = "Explicit CUDA-capable Linux image with Python 3.11 and sufficient disk space."
}
variable "subnet_id" {
  type        = string
  description = "Existing subnet in this zone, with SSH allowed from your IP and HTTPS egress."
}
variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}
