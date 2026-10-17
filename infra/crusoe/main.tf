terraform {
  required_version = ">= 1.6, < 2.0"
  required_providers {
    crusoe = {
      source  = "crusoecloud/crusoe"
      version = "1.1.0"
    }
  }
}

# Infrastructure credentials come from the Crusoe CLI profile; they are distinct
# from CRUSOE_API_KEY used by serverless teacher inference.
provider "crusoe" {
  project = var.project_id
}

resource "crusoe_compute_instance" "trainer" {
  name       = var.name
  project_id = var.project_id
  type       = var.instance_type
  location   = var.location
  image      = var.image
  ssh_key    = file(pathexpand(var.ssh_public_key_path))
  network_interfaces = [{
    subnet      = var.subnet_id
    public_ipv4 = { type = "dynamic" }
  }]
}

output "trainer_id" {
  value = crusoe_compute_instance.trainer.id
}

output "trainer_host" {
  value = crusoe_compute_instance.trainer.external_dns_name
}
