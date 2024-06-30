provider "aws" {
    region = "us-east-2"
}

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

variable "key_pair" {
  description = "AWS Key pair"
  type        = string
  default     = "~/Documentos/Ordenadores/AWS/AWS_par_de_claves.pem"
}

variable "ec2_user" {
  description = "AWS EC2 user"
  type        = string
  default     = "ubuntu"
}

variable "ansible_playbook" {
  description = "Ansible Playbook to execute"
  type        = string
  default     = "playbook.yml"
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
resource "aws_instance" "sttcast" {
# resource "aws_spot_instance_request" "sttcast" {
  ami           = var.sttcast_ami
  instance_type = var.sttcast_instance_type
  vpc_security_group_ids = [aws_security_group.sttcast.id]
  # spot_price = "0.40"
  key_name = "AWS_par_de_claves"
  # wait_for_fulfillment = true
  
  # user_data = <<-EOF
  #             #!/bin/bash
  #             echo "Hello, World" > index.html
  #             nohup busybox httpd -f -p ${var.server_port} &
  #             EOF

  # user_data_replace_on_change = true
  tags = {
    Name = "sttcast_machine"
  }
  
  provisioner "local-exec" {
    command = "echo ${self.public_ip} > inventory ; ANSIBLE_HOST_KEY_CHECKING=False  ansible-playbook -vvv -e 'ec2_instance_id=${self.id}' -u ${var.ec2_user} -i inventory  ${var.ansible_playbook} --private-key '${var.key_pair}' >> result.log "
  } 
}

