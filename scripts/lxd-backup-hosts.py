#!/usr/bin/python
from __future__ import with_statement
from colorama import Fore, Back, Style
from datetime import datetime
from email.mime.text import MIMEText
from tendo import singleton
import inspect
import io
import os
import subprocess
import socket
import string
import sys
import json
import configparser
import paramiko
import StringIO
import time
from time import sleep
import argparse
import MySQLdb
import smtplib
import calendar
import logging
import logging.handlers
from pprint import pprint

# log results
def create_logger():
	# create logger for "Sample App"
	log_runtime = logging.getLogger('automated_runtime')
	log_runtime.setLevel(logging.DEBUG)

	# create file handler which logs even debug messages
	fh = logging.FileHandler('results.log', mode='w')
	fh.setLevel(logging.DEBUG)

	# create console handler with a higher log level
	#ch = logging.StreamHandler(stream=sys.stdout)
	#ch.setLevel(logging.INFO)

	# create formatter and add it to the handlers
	formatter = logging.Formatter('[%(asctime)s] %(message)s ',datefmt='%Y-%m-%d %H:%M:%S')
	fh.setFormatter(formatter)
	#ch.setFormatter(formatter)

	# add the handlers to the logger
	#log_runtime.addHandler(ch)
	log_runtime.addHandler(fh)

	return log_runtime

# mail body
#"lxd backup daily log" 
#backups@marlboro.edu
def output(string, clear = True):
	global print_cache
	global log_runtime

	now = '[' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ']'

	if string is None or string.isspace():
		return
	if(clear):
		print_cache += now + ' ' + string.replace(' ','&nbsp;') + '<br/>\n'
		print string
	else:
		print_cache += now + ' ' + string.replace(' ','&nbsp;')
		print string,

	log_runtime.log(logging.INFO, string)

# output colorful statuses
def show_status(var):
	global print_cache
	global log_runtime

	if var == 0:
		print_cache = print_cache + '[<span style="color:green">OK</span>]<br/>\n'
		print '[' + Fore.GREEN + 'OK' + Fore.RESET + ']'
		log_runtime.log(logging.INFO, 'OK')
	elif var == 1:
		print_cache = print_cache + '[<span style="color:red">FAILURE</span>]<br/>\n'
		print '[' + Fore.RED + 'FAILURE' + Fore.RESET + ']'
		log_runtime.log(logging.INFO, 'FAILURE')
	elif var == 2:
		print_cache = print_cache + '[<span style="color:yellow">BLACKLISTED</span>]<br/>\n'
		print '[' + Fore.YELLOW + 'BLACKLISTED' + Fore.RESET + ']'
		log_runtime.log(logging.INFO, 'BLACKLISTED')
	elif var == 3:
		print_cache = print_cache + '[<span style="color:yellow">UNSCHEDULED</span>]<br/>\n'
		print '[' + Fore.YELLOW + 'UNSCHEDULED' + Fore.RESET + ']'
		log_runtime.log(logging.INFO, 'UNSCHEDULED')
	return

# connect to lxc_host via SSH key
def ssh_connect(lxc_host):
	try:
		output('- Connect to host', False)
		ssh.connect(
			lxc_host['address'],
			key_filename = lxc_host['ssh']['backup_to_host']['key'],
			username = lxc_host['ssh']['backup_to_host']['username'],
			password = lxc_host['ssh']['backup_to_host']['password']
		)
		show_status(0)
		user = ssh_exec('whoami').strip()
		output(' - Logged in as ' + user, True)
		return True
	except paramiko.SSHException:
		show_status(1)
		return False

# ssh exec and output return
def ssh_exec(command):
	# check if still connected
	if ssh.get_transport().is_active() == False:
		output(' Disconnected cannot run command: ', False)
		show_status(1)
		output(command, True)
		return False
	
	# standard input - where process reads to get information from user
	# standard output - where process writes normal information to this file handle
	# standard error - where process writes error information
	stdin, stdout, stderr = ssh.exec_command(command)

	# wait until a response hasn't been seen for timeout period
	# incase command does not return EOF
	timeout = 30
	endtime = time.time() + timeout
	while not stdout.channel.eof_received:
		sleep(1)
		if time.time() > endtime:
			stdout.channel.close()
			break

	string = ''
	for line in stdout.readlines():
		string += line
	return string

# run shell command as subprocess and return output
def shell_exec(command):
	proc = subprocess.Popen(
		command,
		shell = True,
		stdout = subprocess.PIPE,
		stderr = subprocess.PIPE
	)
	string, errors = proc.communicate()
	if errors:
		raise Exception('ERROR: ' + errors)
	return string

# merges two dictionary
def merge_dictionary(x, y):
	z = x.copy()
	z.update(y)
	return z

# display time as HMS
def duration_format(sec_elapsed):
	h = int(sec_elapsed / (60 * 60))
	m = int((sec_elapsed % (60 * 60)) / 60)
	s = sec_elapsed % 60.
	return "{}:{:>02}:{:>05.2f}".format(h, m, s)

# handles CLI arguments
def get_args():
	parser = argparse.ArgumentParser()
	parser.add_argument(
		"-f",
		"--frequency",
		help = "Specify which preservation processes to execute based on config",
		required = True,
		choices = ['hourly','daily','weekly'],
		type = str
	)
	return parser.parse_args()

# get config
def get_config():
	global folder
	global conf
	try:
		folder['current'] = os.path.dirname(os.path.realpath(__file__))

		# load local config
		folder['local_config'] = folder['current'] + '/local-config.json'
		with open(folder['local_config']) as json_file:
			local_conf = json.loads(json_file.read())

		# load hosts config
		folder['hosts_config'] = folder['current'] + '/' \
			+ local_conf['hosts_settings']['config_file']
		with open(folder['hosts_config']) as json_file:
			hosts_conf = json.loads(json_file.read())

		conf = merge_dictionary(local_conf, hosts_conf)
		show_status(0)
		return True
	except:
		show_status(1)
		return False

# get json list of containers and parse for processing
def get_containers():
	output('- Get container list', False)
	try:
		containers = json.loads(ssh_exec('lxc list -cn --format json'))
		show_status(0)
		return containers;
	except:
		show_status(1)
		return;

# remove auto snapshot of a container
def remove_snapshot(container):
	# delete previous snapshot if exists
	try:
		ssh_exec('lxc delete ' + container['name'] + '/auto-backup')
		show_status(0)
	except:
		output('  - Failed to delete auto snapshot', False)
		show_status(1)
		return False

# take auto snapshots of a container
def take_snapshot(container):
	try:
		# take a snapshot of the container
		ssh_exec('lxc snapshot ' + container['name'] + ' auto-backup')
		# check if snapshot folder was made
		check = ssh_exec('if [ -d /var/lib/lxd/snapshots/' + container['name'] + '/auto-backup ]; then echo 1; else echo 0; fi')
		if check.strip() == '1':
			show_status(0)
			return True
		else:
			show_status(1)
			return False
	except:
		show_status(1)
		return False

def backup_host(lxc_host):
	global folder
	global conf
	try:
		# rsync lxc host to backup host
		command = 'rsync -aAXv --progress --delete --stats --exclude={exclude_paths} {host_address}:/ {host_dir}/'.format(
			exclude_paths = ' --exclude='.join(lxc_host['backup']['exclude']),			
			host_address = lxc_host['address'],
			host_dir = folder['host_dir']
		)

		os.system(command)

		# touch host backup to indicate backup processed
		shell_exec('touch ' + folder['host_dir'])

		show_status(0)
		return True
	except:
		output('  - The following command failed on LXC host: ' + command)
		show_status(1)
		return False

def backup_container(lxc_host, container):
	global conf
	global folder

	# find container's storage pool
	output('  - Find container storage pool ',False)
	try:
		# get the location of the contain's storage pool
		container['storage_pool'] = ssh_exec('readlink -f /var/lib/lxd/containers/'+container['name']).strip()
		show_status(0)
		
		folder['container_dir'] = folder['host_dir'] + container['storage_pool'];
		# make container folder on backup if does not exists
		if not os.path.exists(folder['container_dir']):
			output('- Make local folder for copy',False)
			os.makedirs(folder['container_dir'])
			show_status(0)
	except:
		show_status(1)
		pass

	# if container is running stop it
	if container['status'] == "Running":
		#start timer
		start_timer = time.time()
		# output('  - Timer started ')
		# stop container only allow 30 seconds for stopdown to accomidate for hang
		ssh_exec('lxc stop --timeout 30 '+container['name'])
		# after the up to 30 second wait issue a kill command to be sure its stopped
		ssh_exec('lxc stop --force '+container['name'])

		output('  - Stop container [N/A]')
	try:
		# backup the containers storage pool
		exclude_paths = ["/rootfs" + exclude for exclude in container['backup']['exclude']]
		
		command = 'rsync -aAXv --progress --delete --stats --exclude={exclude_paths} {host_address}:{dir_from}/ {dir_to}'.format(
			exclude_paths = ' --exclude='.join(exclude_paths),
			host_address = lxc_host['address'],
			dir_from = container['storage_pool'],
			dir_to = folder['container_dir']
		)
		
		output('  - Copy container (may take a while)... ',False)
		os.system(command)
		show_status(0)	
	except:
		output(' - The following command failed on LXC host: ',False)
		output(command)
		show_status(1)
		pass

	del folder['container_dir'];

	# if container was running start it again
	if container['status'] == "Running":
		end_timer = time.time()
		output('  - Restart container [N/A]')
		ssh_exec('lxc start '+container['name'])

		output('  - Restored after {} of downtime'.format(duration_format(end_timer - start_timer)))

# check to verify the backups are being performed
def check_backup(lxc_host):
	# TODO: make intervault based on config not 1 day
	global conf
	global backups_missed
	global pending_notification

	# 1 day and 1 hour (in case backups take longer)
	frequency = 25 * 60 * 60

	check_folder = lxc_host['backup']['folder'] + '/' + lxc_host['name'] + '/daily/00'
	
	# check if backup folder is from within frequency
	try:
		if os.path.isdir(check_folder):
			mtime = os.path.getmtime(check_folder)
			current = calendar.timegm(time.gmtime())
			if (current - mtime) > frequency:
				pending_notification = True
				backups_missed.append(lxc_host['name'])
				output(' (backup was too long ago)', False)
				return False 
			else:
				return True
		else:
			output(' (folder not made)', False)
			return False
	except Exception,e:
		output(' (failed to perform check)', False)
		return False

def send_notification(subject,message):
	TO = conf['notifications']['receiver']
	FROM = conf['notifications']['sender']
	msg = MIMEText(message, 'html')
	msg['From'] = FROM
	msg['To'] = TO
	msg['Subject'] = subject

	server = smtplib.SMTP('localhost')
	server.sendmail(FROM, TO, msg.as_string())
	server.quit()

def rotate_backup(lxc_host):
	# define lxc hosts rotate directory
	folder['rotate'] = lxc_host['rotate']['folder'] \
		+ '/' + lxc_host['name'] \
		+ '/' + 'daily' + '{}'

	# make rotate folder if does not exists
	if not os.path.isdir(folder['rotate'].format('/')):
		output(' - Make rotate folder: ' + folder['rotate'].format('/'))
		os.makedirs(folder['rotate'].format('/'))

	# delete the oldest folder to make room for new folder
	folder_old = folder['rotate'].format('/' + str(lxc_host['rotate']['copies']).rjust(2, '0'))
	if os.path.isdir(folder_old):
		output(' - Remove the oldest folder: ' + folder_old, False)
		try:
			shell_exec('rm -r ' + folder_old)
			show_status(0)
		except:
			show_status(1)

	# rotate 03 to 04, 02 to 03, 01 to 02, etc.
	rotate_failed = False
	output(' - Rotate backups', False)
	for i in range(lxc_host['rotate']['copies']-1,-1,-1):
		try:
			folder_0 = folder['rotate'].format('/' + str(i).rjust(2, '0'))
			folder_1 = folder['rotate'].format('/' + str(i + 1).rjust(2, '0'))
			if os.path.exists(folder_0) and not os.path.exists(folder_1):
				cmd = 'mv ' + folder_0 + ' ' + folder_1
				shell_exec(cmd)
		except:
			rotate_failed = True
			pass
	if rotate_failed:
		show_status(1)
		output(' - FAIL: ' + cmd)
	else: 
		show_status(0)

	# execute the RSYNC
	output(' - Rotate the latests backup', False)
	try:
		target = folder['rotate'].format('/' + str(0).rjust(2, '0'))
		link = folder['rotate'].format('/' + str(1).rjust(2, '0'))
		if not os.path.isdir(target):
			os.mkdir(target)
		if not os.path.isdir(link):
			cmd = 'rsync -ah --delete -e ssh {source} {target}'.format(link=link, source=folder['host_dir']  + '/', target=target)
		else:
			# hard linking can be verified using "ls -lLi"
			cmd = 'rsync -ah --delete -e ssh --link-dest="{link}" {source} {target}'.format(link=link, source=folder['host_dir'] + '/', target=target)
		os.system(cmd)
		show_status(0)
	except:
		show_status(1)
	
	#TODO: Add capture of cmd stdout to include in output mail log
	os.system('touch {}'.format(target))

def logger(log_type, lxc_host, start_datetime, end_datetime):
	global conf

	if conf['logger']['mysql']['enabled'] == True:
		output('- Insert mysql '),
		# Connect to Codd for storage
		db = MySQLdb.connect(
			host = conf['logger']['mysql']['host'],
			user = conf['logger']['mysql']['user'],
			passwd = conf['logger']['mysql']['password'],
			db = conf['logger']['mysql']['database']
		)
		cursor = db.cursor()
		try:
			if log_type == 'backup':
				output('Log backup', False)
				cursor.execute("INSERT INTO `backupschedule` (`host`, `start`, `end`, `startgroup`, `backupserver`) values (%s,%s,%s,%s,%s)", (
					lxc_host['name'],
					start_datetime,
					end_datetime,
					conf['runtime'],
					conf['local_info']['hostname']))
			elif log_type == 'rotate':
				output('Log rotate',False)
				cursor.execute("INSERT INTO `rotateschedule` (`host`, `start`, `end`, `startgroup`, `backupserver`) values (%s,%s,%s,%s,%s)", (
					lxc_host['name'],
					start_datetime,
					end_datetime,
					conf['runtime'],
					conf['local_info']['hostname']))
			db.commit()
			show_status(0)
		except MySQLdb.Error, e:
			try:
				output("MySQL Error [%d]: %s" % (e.args[0], e.args[1]))
			except IndexError:
				output("MySQL Error: %s" % str(e))
				cursor.close()
			show_status(1)

def main():
	global print_cache
	global folder
	
	for lxc_host_settings in conf['hosts']:
		# register start time for logging
		start_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

		output('\n[[' + lxc_host_settings['name'] + ']]')

		# load defaults host settings without overwriting settings
		lxc_host = merge_dictionary(
			conf['hosts_settings']['default'],
			lxc_host_settings
		)

		# connect to lxc_host or move on
		if ssh_connect(lxc_host) == False:
			output(' - Failed to connect')
			continue

		# setup backup dir for lxc_host
		folder['host_dir'] = lxc_host['backup']['folder'] \
			+ '/' + lxc_host['name'] \
			+ '/' + lxc_host['backup_frequency'] \
			+ '/00'
		if not os.path.exists(folder['host_dir']):
			output('- Make host backup folder: ' + folder['host_dir'])
			os.makedirs(folder['host_dir'])

		# backup hosts root file system
		if args.frequency == lxc_host['backup']['frequency']:
			output('- Backup root file system (may take a while)... ', False)
			backup_host(lxc_host)

		# go through each lxc_host container
		containers = get_containers()
		for container in containers:
			# load container defaults
			container = merge_dictionary(
				container,
				conf['container_settings']
			)
			# load container config override defaults
			if container['name'] in lxc_host['containers']:
				container = merge_dictionary(
					container,
					lxc_host['containers'][container['name']]
				)

			if args.frequency == container['snapshot']['frequency']:
				output('- Delete snapshot "' + container['name'] + '"')
				remove_snapshot(container)
				output('- Take snapshot "' + container['name'] + '"')
				take_snapshot(container)

			if args.frequency == container['backup']['frequency']:
				output('- Backup container "' + container['name'] + '"')
				backup_container(lxc_host, container)

		# close SSH session to host
		output('- Close SSH session')
		ssh.close()

		# end time for logging
		end_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

		# record a log of backup
		logger('backup', lxc_host, start_datetime, end_datetime);

		# check on backups
		output('Check backup', False)
		if check_backup(lxc_host) == True:
			show_status(0)
		else:
			show_status(1)
			output('- Overdue backup')

		#  rotate host's backup
		output('Rotate backup  (may take a while)... ')
		try:
			rotate_backup(lxc_host)
		except:
			output(' - status', False)
			show_status(1)

	# check to send notification of backup failure detected
	if pending_notification == True:
		send_notification('LXD Backup Overdue/Failed', 'The following backup were not completed within the last 24 hours:\n' + \
			 ',\n'.join(backups_missed)
		)
		output('Overdue notification sent')

if __name__ == "__main__":
	# only allow one instance at a time
	me = singleton.SingleInstance()

	# set config
	global args
	global conf
	global ssh
	global folder
	global pending_notification
	global backup_missed
	global print_cache
	global log_runtime

	print_cache = ''
	args = get_args()
	folder = {}
	pending_notification = False
	backups_missed = []

	# create logging 
	log_runtime = create_logger()

	# begin stout
	output('<- START ->\n')
	output('Load config.json', False)

	if get_config() == True:
		conf['runtime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

		# if exists remove transfer log
		try:
			os.remove('transfer.log')
		except OSError:
			pass

		# make transfer log
		os.mknod('transfer.log')
		
		# declare ssh client
		ssh = paramiko.SSHClient()
		# automatically add remote host keys
		ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		# keep connection alive
		# ?? set_keepalive(30)
		# create a log file for SSH because stdout may be large during rsync
		paramiko.util.log_to_file('transfer.log')

		main()

		# remove transfer log when done
		try:
			os.remove('transfer.log')
		except OSError:
			pass

	# convey the script has completed
	output('<- END ->', True)
	
	# send back up log
	send_notification('LXD Backup Log', print_cache)
	output('Backup log notification sent')
