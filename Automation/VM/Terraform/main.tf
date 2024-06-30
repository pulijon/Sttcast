
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

variable "payload_directory" {
  description = "Local directory to upload content from"
  type        = string
  default     = "/vagrant/Payload"
}

data "aws_caller_identity" "current" {}

provider "aws" {
    region = "us-east-2"
    access_key = var.AWS_ACCESS_KEY_ID
    secret_key = var.AWS_SECRET_ACCESS_KEY
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

resource "aws_s3_bucket" "sttcast_payload_bucket" {
  bucket = "sttcast-payload"
}

# resource "aws_s3_bucket_acl" "sttcast_payload_bucket_acl" {
#   depends_on = [aws_s3_bucket.sttcast_payload_bucket]
#   bucket = aws_s3_bucket.sttcast_payload_bucket.id
#   acl    = "private"
# }


locals {
  mp3_files = fileset(var.payload_directory, "*.mp3")
}


resource "aws_key_pair" "vm_keypair" {
  key_name   = var.sttcast_key_pair
  public_key = file("${var.user_home}/.ssh/id_rsa.pub")
}

resource "aws_iam_role" "sttcast_role" {
  name = "sttcast_role_ec2_s3"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}


# resource "aws_iam_role_policy_attachment" "s3_full_access" {
#   role       = aws_iam_role.sttcast_role.name
#   policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
# }

resource "aws_s3_bucket_policy" "sttcast_payload_bucket_policy" {
  bucket = aws_s3_bucket.sttcast_payload_bucket.id
  depends_on = [aws_iam_role.sttcast_role]

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          AWS = data.aws_caller_identity.current.arn
        },
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ],
       Resource = [
              "${aws_s3_bucket.sttcast_payload_bucket.arn}",
              "${aws_s3_bucket.sttcast_payload_bucket.arn}/*",
        ],
      },
      {
        Effect = "Allow",
        Principal = {
           AWS = "${aws_iam_role.sttcast_role.arn}"
        },
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
              "${aws_s3_bucket.sttcast_payload_bucket.arn}",
              "${aws_s3_bucket.sttcast_payload_bucket.arn}/*",
        ],
      },
    ]
  })
}

resource "aws_s3_object" "mp3" {
  depends_on = [ 
    aws_s3_bucket_policy.sttcast_payload_bucket_policy
   ]
  for_each = { for f in local.mp3_files : f => f }
  bucket   = aws_s3_bucket.sttcast_payload_bucket.bucket 
  key      = each.value
  source   = "${var.payload_directory}/${each.value}"
}

resource "aws_iam_instance_profile" "sttcast_profile_iam" {
  depends_on = [aws_iam_role.sttcast_role]

  name = "sttcast_profile_iam"
  role = aws_iam_role.sttcast_role.name
}

resource "aws_instance" "sttcast" {
  depends_on = [aws_security_group.sttcast, 
                aws_key_pair.vm_keypair,
                aws_s3_object.mp3,
                aws_iam_instance_profile.sttcast_profile_iam,]
  ami           = var.sttcast_ami
  instance_type = var.sttcast_instance_type
  vpc_security_group_ids = [aws_security_group.sttcast.id]
  key_name = var.sttcast_key_pair
  iam_instance_profile = aws_iam_instance_profile.sttcast_profile_iam.name
 
  tags = {
    Name = "sttcast_machine"
  }
  
  provisioner "local-exec" {
    command = <<-EOF
       cd ${var.ansible_dir}
       echo ${self.public_ip} > inventory 
       ANSIBLE_HOST_KEY_CHECKING=false  ansible-playbook -v \
         -e 'ec2_instance_id=${self.id}' \
         -u ${var.ec2_user} \
         -i inventory  \
         ${var.ansible_playbook} \
         --private-key '${var.user_home}/.ssh/id_rsa' \
        >> result.log
    EOF
  } 
}
output "public_ip" {
  description = "The public IP address of the web server"
  # value = aws_spot_instance_request.sttcast.public_ip
  value = aws_instance.sttcast.public_ip
}

