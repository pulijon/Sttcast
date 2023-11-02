
include stdlib
include apt

file {'/home/vagrant/README':
    ensure => file,
    content => "VM to run terraform and ansible automation for sttcast",
    owner => 'vagrant',
    mode => '0444',
}


$packages = [
    'vim',
    'ansible',
    'tree',
    'mlocate',
    'build-essential',
    'git',
    'docker',
    'docker-compose',
    'nmon',
    # 'kubernetes-client',
    # 'gnome',
    # 'x11-apps',
]


apt::source {'terraform':
    location    => 'https://apt.releases.hashicorp.com',
    release     => "bookworm",
    repos       => 'main',
    key         => {
      'id'     => '72D7468F', # Reemplaza con el ID de la clave GPG si lo conoces
      source => 'https://apt.releases.hashicorp.com/gpg',
    },
    include     => {
      src   => false,
      deb   => true,
    },
}->
exec {"install terraform":
  command => "/usr/bin/apt update;  DEBIAN_FRONTEND=noninteractive apt install --force-yes terraform"
}

package {$packages:
    ensure => installed,
}

service {'docker':
  ensure => running,
  enable => true
}

exec {"updatedb":
  command => "/usr/bin/updatedb",
  subscribe => Package["mlocate"]
}

user {"vagrant":
    ensure => present,
    groups => "docker",
    require => Package['docker']
}

exec {"terraform init":
  command => "/usr/bin/terraform init",
  cwd => "/vagrant/Terraform",
  user => "vagrant",
  group => "vagrant",
  path =>["/usr/local/bin",
          "/usr/bin",
          "/bin"],
  require => Exec["install terraform"],
  creates => "/vagrant/Terraform/terraform.tfstate"
}

$key_file='/home/vagrant/.ssh/id_rsa'
exec {'generate ssh key':
  command => "/usr/bin/ssh-keygen -t rsa -f ${key_file} -N ''",
  creates => $key_file,
  user => vagrant,
  group => vagrant,
  path =>["/usr/local/bin",
          "/usr/bin",
          "/bin"],
}


