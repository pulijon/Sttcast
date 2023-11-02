
variable "ssh_port" {
  description = "The port the server will use for SSH requests"
  type        = number
  default     = 22
}

variable "sttcast_instance_type" {
  description = "Instance type for sttcast"
  type        = string
  default     = "g4dn.xlarge"
}

variable "AWS_SECRET_ACCESS_KEY" {
  description = "Secret Key for AWS"
  type        = string
  sensitive   = true
}

variable "AWS_ACCESS_KEY_ID" {
  description = "Key ID for AWS"
  type        = string
  sensitive   = true
}

variable "sttcast_ami" {
  description = "AMI for sttcast"
  type        = string
  default     = "ami-0e0d36dffd7ce3f68"
}

variable "ec2_user" {
  description = "AWS EC2 user"
  type        = string
  default     = "ubuntu"
}

variable "ansible_dir" {
  description = "Ansible directory"
  type        = string
  default     = "/vagrant/Ansible"
}

variable "ansible_playbook" {
  description = "Ansible Playbook to execute"
  type        = string
  default     = "playbook.yml"
}

variable "sttcast_key_pair" {
  description = "Name of key par for ansible execution"
  type        = string
  default     = "sttcast_key_pair"
}

variable "user_home" {
  description = "Home of user executing terraform"
  type        = string
  default     = "/home/vagrant"
}

provider "aws" {
    region = "us-east-2"
    access_key = var.AWS_ACCESS_KEY_ID
    secret_key = var.AWS_SECRET_ACCESS_KEY
}

output "public_ip" {
  description = "The public IP address of the web server"
  # value = aws_spot_instance_request.sttcast.public_ip
  value = aws_instance.sttcast.public_ip
}

resource "aws_security_group" "sttcast" {
  name = "security_group_ssh"

  ingress {
    from_port   = var.ssh_port
    to_port     = var.ssh_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_key_pair" "vm_keypair" {
  key_name   = var.sttcast_key_pair
  public_key = file("${var.user_home}/.ssh/id_rsa.pub")
}

resource "aws_instance" "sttcast" {
  depends_on = [aws_security_group.sttcast, aws_key_pair.vm_keypair]
  ami           = var.sttcast_ami
  instance_type = var.sttcast_instance_type
  vpc_security_group_ids = [aws_security_group.sttcast.id]
  key_name = var.sttcast_key_pair
 
  tags = {
    Name = "sttcast_machine"
  }
  
  provisioner "local-exec" {
    command = <<-EOF
       cd ${var.ansible_dir}
       echo ${self.public_ip} > inventory 
       ANSIBLE_HOST_KEY_CHECKING=false  ansible-playbook -vv \
         -e 'ec2_instance_id=${self.id}' \
         -u ${var.ec2_user} \
         -i inventory  \
         ${var.ansible_playbook} \
         --private-key '${var.user_home}/.ssh/id_rsa' \
        >> result.log
    EOF
  } 
}

