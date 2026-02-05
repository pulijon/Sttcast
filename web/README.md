# Caution
Subir ficheros a S3 tiene un coste asociado al almacenamiento y a la transferencia de datos

**El usuario debe ser consciente de ese coste, de supervisarlo y de establecer los oportunos mecanismos para evitar incurrir en extracostes**

# Rationale for Web

Una vez que se tienen varios audios transcritos (por ejemplo, la colección de un podcast), surge la necesidad de almacenarlos y acceder a ellos de la mejor forma posible. También la de compartir, siempre que se disponga de los permisos necesarios, con otros usuarios. Los propios productores de podcasts pueden estar interesados en una publicación que realce el trabajo realizado.

Hacer sitios web no es complejo, pero requiere un cierto conocimiento de las tecnologías web y disponer de infraestructura para desplegar el portal. La nube nos permite una forma muy sencilla y cómoda para publicar los podcasts. En el caso de Amazon AWS se pueden subir los ficheros de audio y los de transcripciones, acompañados de un indexador html que permite seleccionar lo que se quiere ver.

Esta parte del proyecto Sttcast automatiza todo esto para obtener un sitio web público estático con las transcripciones.

# Requirements

## HW

* Processor with 4 cores and 2.4 MHz of clock
* RAM: 8 GB
* HDD: free 10 GB.

## SW

* SO windows, Linux or IOS
* Python >= 3.10
* Git


## AWS
You must have an account in Amazon AWS with valid credentials (```AWS_ACCESS_KEY_ID``` and ```AWS_SECRET_ACCESS_KEY```) to boot an **EC2** instance with **GPU** (if your account does not allow you to boot that instance, you shoul open a ticket with Amazon)

# User guide
## Bajarse el software de GitHub


## Copy the contents of Automation/VM

Crear un directorio de trabajo (supongamos que se llama **workdir**)

Copiar los mp3 a **workdir**

Ir al directorio con la copia git (supongamos **repolocal**)

## Copying the mp3 files to Payload dir

The mp3 files to transcript has to be copied in the Payload subdir as it is shown in the figure

![](payload_dir.png)

## Creating the Virtual Machine

With a Windows console (cmd, PowerShell, Git bash, etc.), go to that directory and execute **vagrant up**. After a bunch of lines, vagrant will indicate that everything has gone well and will display the line **Notice: Applied catalog in x seconds** 

```console
C:\VagBoxes\Sttcast\VM>vagrant up
Bringing machine 'sttcast' up with 'virtualbox' provider...
==> sttcast: Importing base box 'bento/debian-12'...
==> sttcast: Matching MAC address for NAT networking...
==> sttcast: Checking if box 'bento/debian-12' version '202309.08.0' is up to date...
==> sttcast: Setting the name of the VM: VM_sttcast_1699034156616_84360
...

...
==> sttcast: Notice: /Stage[main]/Main/Apt::Source[terraform]/Apt::Setting[list-terraform]/File[/etc/apt/sources.list.d/terraform.list]/ensure: defined content as '{sha256}12e56579d63b0aea920f409b94d47435f834a2351cbef61cc11b8f554224d5c9'
==> sttcast: Notice: /Stage[main]/Apt::Update/Exec[apt_update]: Triggered 'refresh' from 1 event
==> sttcast: Notice: /Stage[main]/Main/Exec[install terraform]/returns: executed successfully
==> sttcast: Notice: Applied catalog in 195.46 seconds
```

## Entering the VM 

The VM is a Linux Debian 12 (stable distribution at the time of writing this document). To enter in it you should type  ```vagrant ssh```

```console
C:\VagBoxes\Sttcast\VM>vagrant ssh
Linux sttcast 6.1.0-11-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.1.38-4 (2023-08-08) x86_64

This system is built by the Bento project by Chef Software
More information can be found at https://github.com/chef/bento

The programs included with the Debian GNU/Linux system are free software;
the exact distribution terms for each program are described in the
individual files in /usr/share/doc/*/copyright.

Debian GNU/Linux comes with ABSOLUTELY NO WARRANTY, to the extent
permitted by applicable law.
vagrant@sttcast:~$
```
<!-- This is done in the provision of the Virtual Machine
## Initializing terraform (only the first time)

You must go to the **Terraform** dir and execute **terraform init** . This step is only necessary with a brand new machine created.
```bash
vagrant@sttcast:/vagrant/Terraform$ terraform init

Initializing the backend...

Initializing provider plugins...
- Reusing previous version of hashicorp/aws from the dependency lock file
- Using previously-installed hashicorp/aws v5.23.1

Terraform has been successfully initialized!

You may now begin working with Terraform. Try running "terraform plan" to see
any changes that are required for your infrastructure. All Terraform commands
should now work.

If you ever set or change modules or backend configuration for Terraform,
rerun this command to reinitialize your working directory. If you forget, other
commands will detect it and remind you to do so if necessary.
```
 -->
## Executing the job
From the directory /vagrant/Terraform, execute ```terraform apply -auto--approve```. terraform will ask you for your AWS credentials (the program will not ask for them if you have previously configured the environment vars ```TF_VAR_AWS_ACCESS_KEY_ID``` and ```TF_VAR_AWS_SECRET_ACCESS_KEY```)

```bash
vagrant@sttcast:/vagrant/Terraform$ terraform apply -auto-approve
var.AWS_ACCESS_KEY_ID
  Key ID for AWS

  Enter a value:

var.AWS_SECRET_ACCESS_KEY
  Secret Key for AWS

  Enter a value:


Terraform used the selected providers to generate the following execution plan. Resource actions are indicated with the
following symbols:
...

...

aws_instance.sttcast: Still creating... [37m21s elapsed]
aws_instance.sttcast: Still creating... [37m31s elapsed]
aws_instance.sttcast: Still creating... [37m41s elapsed]
aws_instance.sttcast: Still creating... [37m51s elapsed]
aws_instance.sttcast: Creation complete after 37m52s [id=i-0357318d0caa302d5]

Apply complete! Resources: 3 added, 0 changed, 0 destroyed.

Outputs:

public_ip = "X.X.X.X"
```

You should see in the Payload directory the results as shown in the image:

![](payload_after_terraform_apply.png)

Filenames ended in whisper.html are the transcriptions in HTML format without player embedded. 

![](html_without_player.png)

Filenames ended in whisper_audio.html are transcriptions in HTML format with player embedded

![](html_with_player.png)

## Destroying the resources

The terraform configuration destroy the expensive g4dn machine. However, you should realize that if the instance is not destroyed, it could be very expensive as you pay for it while it's alive. Remember the  **Caution note** at the beginning of this document. 

You have to destroy the resources with ```terraform destroy -auto--aprove```

```bash
vagrant@sttcast:/vagrant/Terraform$ terraform destroy -auto-approve
var.AWS_ACCESS_KEY_ID
  Key ID for AWS

  Enter a value:

var.AWS_SECRET_ACCESS_KEY
  Secret Key for AWS

  Enter a value:

aws_key_pair.vm_keypair: Refreshing state... [id=sttcast_key_pair]
aws_security_group.sttcast: Refreshing state... [id=sg-0d7a598806daeb09e]
...

...
aws_security_group.sttcast: Destroying... [id=sg-0d7a598806daeb09e]
aws_key_pair.vm_keypair: Destroying... [id=sttcast_key_pair]
aws_key_pair.vm_keypair: Destruction complete after 0s
aws_security_group.sttcast: Destruction complete after 1s

Destroy complete! Resources: 3 destroyed.
```
In order to be sure it has worked, the command **terraform state** should not show anything

```bash
vagrant@sttcast:/vagrant/Terraform$ terraform state list
vagrant@sttcast:/vagrant/Terraform$
```
## Primer on vagrant

I often tell my students that Vagrant is like "Las Vegas," or like a football dressing room. What happens in vagrant, stays in Vagrant. That is, although one might think that once the machine is created with Vagrant, you could use the VirtualBox console (the provisioner used for this project, though Vagrant can work with other hypervisors or even with containers) to start or stop the machines, this is not the case. You have to use Vagrant to start, shutdown, or reprovision.

To start the VM at any time (not only the first one)

```console
C:\VagBoxes\Sttcast\VM>vagrant start
```
To enter in a console ssh session in the VM at any time 

```console
C:\VagBoxes\Sttcast\VM>vagrant ssh
```

To shutdown the machine, you should type:

```console
C:\VagBoxes\Sttcast\VM>vagrant halt
```

To destroy the VM

```console
C:\VagBoxes\Sttcast\VM>vagrant destroy
```

To see the status of vagrants machines

```console
C:\VagBoxes\Sttcast\VM>vagrant global-status
```

The ```status``` of VMs allows us to acces to their ```ids```, with this ids (even with the two or three firs characters, you could execute the previous commands from any directory)

```
c:\Users\jmrob>vagrant <command> <id>
```

## Shutting down the VM

As stated previously, the VM can be shutted down with ```vagrant halt``` executed from the directory of the VM (or, whith the id of the machine obtained throug ```vagrant global-status```, with ```vagrant halt <id>```)

```
C:\VagBoxes\Sttcast\VM>vagrant halt
==> sttcast: Attempting graceful shutdown of VM...
```

## Configuration

Each run of ```terraform``` makes use of ```ansible``` and ```ansible``` can be configured with the file ```Ansible/vars.yml``` and the the files ```vars/main.yml``` in subdirectories from ```Automation/VM/Ansible/roles```.

Specifically, the file Ansible ```/roles/app_exec/vars/main.yml``` contains the execution parameters for sttcast:

```yaml
# Configure sttcast
whmodel:    "small"
seconds:    "36000"
cpus:       "6"
min_offset: "60"
max_gap:    "0.8"
html_suffix: "whisper"
mp3_extension: ".mp3"
html_extension: "_{{ html_suffix }}.html"
audio_extension: "_{{ html_suffix }}_audio.html"
```

Terraform has variables that could be overwritten by enfironment variables that should be named as the terraform variable prefixed by TF_VAR, so if you want to change the g4dn.2xlarge to g4dn.xlarge, you should set the environment variable TF_VAR_sttcast_instance_typo as below:

```bash
export TF_VAR_sttcast_instance_type="g4dn.xlarge"
```

Some of the terraform variables are shown here

```hcl


variable "sttcast_instance_type" {
  description = "Instance type for sttcast"
  type        = string
  default     = "g4dn.2xlarge"
}

variable "sttcast_spot_price" {
  description = "Instance type for sttcast"
  type        = string
  default     = "0.28"
}

variable "sttcast_ami" {
  description = "AMI for sttcast"
  type        = string
  # Instance CUDA TensorFlow
  # default     = "ami-0e0d36dffd7ce3f68"
  # Instance Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.3.0 (Ubuntu 20.04) 20240611
  # default = "ami-0c540ca1e5211e422"
  # Instance Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04) 20240624
  default     = "ami-0fa7c50f46a48ae63"
}

variable "payload_directory" {
  description = "Local directory to upload content from"
  type        = string
  default     = "/vagrant/Payload"
}

```

You may want to change this parameters to best fit the behaviour to your needs.

## To Do

Many modifications can be made and will be made in the future.

* To save costs, the most obvious change is to use intermediate S3 storage for the **payload**. A significant portion of the execution time is spent copying the MP3 files to the target machine. The upload time from **S3** is assumed to be much faster (and therefore cheaper) for the machine with **GPU**. One could even consider **EBS**, although I would like to conduct tests. **(Done 2023-11-06)**

  







