# LXD Host Backup
(this project was since replaced with Ansible version, in LXD Cloud)

Use this to backup an LXD server farm at set frequency. It works by connecting using an SSH key array of LXD hosts that are specified in config.json. Once connected the script rsyncs the root dir and then snapshots, stops, copies, and restarts each the container as defined. It also handles rotates using hard links. Notifications are sent when backups fail.

## Recommended
* Ubuntu Server 16 (Tested).

## Dependencies
The following packages are required:
```
apt-get install python-pip
pip install --upgrade pip
pip install configparser
pip install paramiko
pip install colorama
pip install tendo
```

###Ubuntu Server 14
The following packages were required to install paramiko on Ubuntu Server 14; they were not required for Ubuntu Server 16.
```
sudo apt-get install libffi-dev libssl-dev python-dev
```

## Setup New Host
To setup a new LXD host we have to generate one key to connect to the host and another key to connect back to the backup server. This process is detailed below.

### SSH Key From Backup To Host
On the backup server, where this script should reside, run the command.
```
ssh-keygen -t rsa -b 2048
```

Enter file in which to save the key (/root/.ssh/id_rsa): >/root/.ssh/[HOST NAME]     

Enter passphrase (empty for no passphrase):
> [PASSWORD]

Enter same passphrase again:
> [PASSWORD]

Then either push the key to the LXD host. If root SSH is not enable, you must manual complete the following:
```
cat /root/.ssh/[HOST NAME].pub | ssh root@[HOST ADDRESS] 'cat - >> ~/.ssh/authorized_keys'
```

Add the item to /root/.ssh/config
```
# backup server
Host [HOST NAME]
PubkeyAuthentication yes
IdentityFile ~/.ssh/[HOST NAME]
```

For more information about using SSH keys, visit http://alblue.bandlem.com/2005/08/howto-ssh-logins-using-keys.html

### SSH Key From Host To Backup
First, enable root SSH access on the backup server by completing the following:
```
# set password for root
sudo passwd
# enable root SSH
sudo sed -i 's/prohibit-password/yes/' /etc/ssh/sshd_config
# restart ssh daemon
sudo systemctl restart sshd
```

Next generate a key to the backup server. For simplicity sakes, this key does not feature a password. On the LXD host, which is not where this script should reside, run the following commands:
```
ssh-keygen -t rsa -b 2048
Enter file in which to save the key (/root/.ssh/id_rsa): /root/.ssh/backup     
Enter passphrase (empty for no passphrase): [NONE]
Enter same passphrase again: [NONE]
```

As before either push the public key to the backup server or place it there.
```
cat /root/.ssh/backup.pub | ssh root@[BACKUP SERVER ADDRESS] 'cat - >> ~/.ssh/authorized_keys'
service ssh restart
```

Add the item to /root/.ssh/config
```
# backup server
Host [BACKUP SERVER ADDRESS]
PubkeyAuthentication yes
IdentityFile ~/.ssh/backup
```

## Setup config.json
Copy the sample-config.json file to local-config.json and update the setting to reflect the local backup server. Add individual LXD hosts backup info to the hosts-config.json file (or other file if different specified in local-config.json).

It is recommended exclude the LXD storage pools initially because there may be a database running that need to be stopped during copy to avoid corruption (e.g. MySQL). The /var/lib/lxc folder is generally excluded in the sample config because the focus is LXD; not LXC.

### Multiple Backup Hosts
To make managing multiple backup machines easier, create a uniquely named host-config.json file for each backup machine and specify its use in the local-config.json file. By doing so a centralized list of highly specific host settings can be maintained in a centralized repo.

## Consider Backup Mounts
Due to space limitations, you may want to consider using different hard drives to store different hosts backups. This can be accomplished by adding a symlink from the [BACKUP] directory to the hard drive. For example, to store LXD hosts Barney, Bear, Bolsa, and Cartman on different hard drives we could create the following symlinks:
```
ln -s /disk/1/barney /backup/barney
ln -s /disk/2/bear /backup/bear
ln -s /disk/3/bolsa /backup/bolsa
ln -s /disk/4/cartman /backup/cartman
```
To ensure this symlink still works on reboot, make certain the hard drive the symlink points has an auto mount in fstab.

## Enable Cron
Before enabling cron jobs of the script on the backup server, it is a good idea to test the script by running the following:
```
sudo python lxd-backup-hosts.py -f=daily
```

```
If everything backups accordingly, then create the cron jobs.
>    ┌───────────── minute (0 - 59)
>    │ ┌───────────── hour (0 - 23)
>    │ │ ┌───────────── day of month (1 - 31)
>    │ │ │ ┌───────────── month (1 - 12)
>    │ │ │ │ ┌───────────── day of week (0 - 6) (Sunday to Saturday;
>    │ │ │ │ │                  7 is also Sunday)
>    │ │ │ │ │
>    * * * * 7  python lxd-backup-hosts.py --frequency=weekly
>   15 3 * * *  python lxd-backup-hosts.py --frequency=daily
>    0 * * * *  python lxd-backup-hosts.py --frequency=hourly
```
