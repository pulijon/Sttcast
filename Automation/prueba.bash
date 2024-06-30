ansible-playbook -vv \
	-e 'ec2_instance_id=i-0557f418a37bbee01' \
	-u 'ubuntu' \
	-i 'inventory' \
	playbook.yml \
	--private-key '/home/jmrobles/Documentos/Ordenadores/AWS/AWS_par_de_claves.pem'
