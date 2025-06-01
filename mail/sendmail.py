#!/usr/bin/env python3
"""
A barebones script to forward email from stdin to a remote sendmail via SSH.
It reads SSH and remote sendmail parameters from configuration files,
environment variables, and command-line arguments.

Configuration precedence:
1. Command-line arguments
2. Environment variables
3. User config file (~/.sendmailrc)
4. Global config file (/etc/sendmailrc)
5. Hardcoded defaults

Example config file:
[SSH]
Host = mailrelay.example.com
User = sendmail_forwarder
# Port = 22
# KeyFile = /etc/ssh/sendmail_forwarder_key
RemoteSendmailPath = /usr/sbin/sendmail
# RemoteSendmailOptions = -oi
# Verbose = false

"""

import sys
import os
import argparse
import subprocess
import shlex
import configparser

# --- Default Configuration Values ---
DEFAULT_SSH_PORT = 22
DEFAULT_REMOTE_SENDMAIL_PATH = "/usr/sbin/sendmail"
DEFAULT_REMOTE_SENDMAIL_OPTIONS = "" # e.g., "-t -oi"
DEFAULT_VERBOSE = False

# --- Configuration File Paths ---
GLOBAL_CONFIG_FILE = '/etc/sendmailrc'
USER_CONFIG_FILE = os.path.expanduser('~/.sendmailrc')

# --- Environment Variable Prefixes ---
ENV_PREFIX = "SENDMAILPY_"

def load_config_from_files(cfg_to_update: dict):
    """
    Loads configuration from global and user config files.
    User config overrides global config.
    Updates the provided cfg_to_update dictionary.
    """
    parser = configparser.ConfigParser()
    # Read files in order: global first, then user (user values will override global)
    files_read = parser.read([GLOBAL_CONFIG_FILE, USER_CONFIG_FILE])

    for f_path in files_read:
        if cfg_to_update.get('verbose', DEFAULT_VERBOSE):
            print(f"Info: Reading configuration from {f_path}", file=sys.stderr)

    if 'SSH' in parser:
        ssh_section = parser['SSH']
        cfg_to_update['ssh_host'] = ssh_section.get('Host', cfg_to_update.get('ssh_host'))
        cfg_to_update['ssh_user'] = ssh_section.get('User', cfg_to_update.get('ssh_user'))
        # Ensure port is int, fallback to existing or default if conversion fails
        try:
            cfg_to_update['ssh_port'] = ssh_section.getint('Port', cfg_to_update.get('ssh_port'))
        except ValueError:
            if cfg_to_update.get('verbose', DEFAULT_VERBOSE):
                print(f"Warning: Invalid Port value in config. Using {cfg_to_update.get('ssh_port')}.", file=sys.stderr)

        cfg_to_update['ssh_key_file'] = ssh_section.get('KeyFile', cfg_to_update.get('ssh_key_file'))
        cfg_to_update['remote_sendmail_path'] = ssh_section.get('RemoteSendmailPath', cfg_to_update.get('remote_sendmail_path'))
        cfg_to_update['remote_sendmail_options'] = ssh_section.get('RemoteSendmailOptions', cfg_to_update.get('remote_sendmail_options'))
        # Verbose can also be in config
        try:
            cfg_to_update['verbose'] = ssh_section.getboolean('Verbose', cfg_to_update.get('verbose'))
        except ValueError:
             if cfg_to_update.get('verbose', DEFAULT_VERBOSE): # Check initial verbose if current is not set
                print(f"Warning: Invalid Verbose value in config. Using {cfg_to_update.get('verbose')}.", file=sys.stderr)


def get_env_var(var_name: str, default_value: any, type_conv=str):
    """Gets an environment variable with a prefix, applying type conversion."""
    env_val_str = os.getenv(f"{ENV_PREFIX}{var_name}")
    if env_val_str is not None:
        try:
            return type_conv(env_val_str)
        except ValueError:
            print(f"Warning: Invalid environment variable {ENV_PREFIX}{var_name}='{env_val_str}'. Using default/config.", file=sys.stderr)
    return default_value

def main():
    # 1. Initialize configuration with hardcoded defaults
    config = {
        'ssh_host': None,
        'ssh_user': None,
        'ssh_port': DEFAULT_SSH_PORT,
        'ssh_key_file': None,
        'remote_sendmail_path': DEFAULT_REMOTE_SENDMAIL_PATH,
        'remote_sendmail_options': DEFAULT_REMOTE_SENDMAIL_OPTIONS,
        'verbose': DEFAULT_VERBOSE,
        'recipients': []
    }

    # 2. Load configuration from files (updates config dict)
    load_config_from_files(config)

    # 3. Prepare argparse, using values from (Defaults -> Config Files -> Env) as defaults for CLI args
    #    The ArgumentDefaultsHelpFormatter shows these defaults in --help
    parser = argparse.ArgumentParser(
        description="Forward email from stdin to remote sendmail via SSH.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Helper to get default for argparse, respecting ENV > Config > Hardcoded default
    def arg_default(env_key_suffix, config_key, type_conv=str):
        return get_env_var(env_key_suffix, config[config_key], type_conv)

    # SSH Arguments
    parser.add_argument('--ssh-host', type=str,
                        default=arg_default('SSH_HOST', 'ssh_host'),
                        help="Remote SSH host.")
    parser.add_argument('--ssh-user', type=str,
                        default=arg_default('SSH_USER', 'ssh_user'),
                        help="SSH username.")
    parser.add_argument('--ssh-port', type=int,
                        default=arg_default('SSH_PORT', 'ssh_port', int),
                        help="SSH port.")
    parser.add_argument('--ssh-key-file', type=str,
                        default=arg_default('SSH_KEY_FILE', 'ssh_key_file'),
                        help="Path to SSH private key file.")

    # Remote Sendmail Arguments
    parser.add_argument('--remote-sendmail-path', type=str,
                        default=arg_default('REMOTE_SENDMAIL_PATH', 'remote_sendmail_path'),
                        help="Path to sendmail executable on the remote host.")
    parser.add_argument('--remote-sendmail-options', type=str,
                        default=arg_default('REMOTE_SENDMAIL_OPTIONS', 'remote_sendmail_options'),
                        help="Options to pass to the remote sendmail command (e.g., '-t -oi').")

    # Other Arguments
    verbose_env_str = os.getenv(f"{ENV_PREFIX}VERBOSE", str(config['verbose'])).lower()
    parser.add_argument('-v', '--verbose', action='store_true',
                        default=(verbose_env_str == 'true'),
                        help="Enable verbose output.")
    parser.add_argument('recipients', nargs='*',
                        help="Recipient email addresses. Usually not needed if '-t' is in remote_sendmail_options.")

    args = parser.parse_args()

    # 4. Final configuration is now in `args` object, respecting full precedence.
    #    (CLI > ENV > User Config > Global Config > Defaults)

    # Validation
    if not args.ssh_host:
        parser.error("SSH host is required. Set via --ssh-host, environment, or config file.")
    if not args.ssh_user:
        parser.error("SSH user is required. Set via --ssh-user, environment, or config file.")

    remote_opts_str = args.remote_sendmail_options if args.remote_sendmail_options else ""
    if '-t' not in remote_opts_str.split() and not args.recipients:
        parser.error("Recipients must be provided on the command line if '-t' is not part of --remote-sendmail-options.")

    # 5. Read the entire email message from stdin
    email_message = sys.stdin.read()

    # 6. Construct the SSH command
    ssh_command = ['ssh']

    # --- Add BatchMode to ensure non-interactive operation ---
    ssh_command.extend(['-o', 'BatchMode=yes'])
    # --- End of addition ---

    if args.ssh_port != DEFAULT_SSH_PORT: # Only add if not default
        ssh_command.extend(['-p', str(args.ssh_port)])
    if args.ssh_key_file:
        ssh_command.extend(['-i', args.ssh_key_file])
    ssh_command.append(f"{args.ssh_user}@{args.ssh_host}")

    # Construct the remote sendmail command string
    remote_sendmail_cmd_parts = [shlex.quote(args.remote_sendmail_path)]
    if remote_opts_str:
        # shlex.split handles options that might be quoted, e.g., "-F 'Sender Name'"
        remote_sendmail_cmd_parts.extend(shlex.split(remote_opts_str))
    if args.recipients:
        remote_sendmail_cmd_parts.extend([shlex.quote(rcpt) for rcpt in args.recipients])
    
    full_remote_command = ' '.join(remote_sendmail_cmd_parts)
    ssh_command.append(full_remote_command)

    if args.verbose:
        print(f"Info: Attempting to send email via: {' '.join(ssh_command)}", file=sys.stderr)
        print(f"Info: Remote sendmail command: {full_remote_command}", file=sys.stderr)
        if len(email_message) > 500:
            print(f"Info: Email message (first 500 chars):\n{email_message[:500]}...", file=sys.stderr)
        else:
            print(f"Info: Email message:\n{email_message}", file=sys.stderr)
        print("---", file=sys.stderr)


    # 7. Execute the command
    try:
        process = subprocess.Popen(
            ssh_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='replace' # Handle potential encoding issues in the email message
        )
        stdout, stderr = process.communicate(input=email_message)

        if process.returncode != 0:
            print(f"Error: SSH/Sendmail command failed with exit code {process.returncode}", file=sys.stderr)
            if stdout:
                print(f"Stdout:\n{stdout}", file=sys.stderr)
            if stderr:
                print(f"Stderr:\n{stderr}", file=sys.stderr)
            sys.exit(process.returncode)
        
        if args.verbose:
            print("Info: Email sent successfully.", file=sys.stderr)
            if stdout:
                print(f"Stdout:\n{stdout}", file=sys.stderr)
            if stderr: # sendmail -v often prints to stderr even on success
                print(f"Stderr:\n{stderr}", file=sys.stderr)
        sys.exit(0)

    except FileNotFoundError:
        print(f"Error: The 'ssh' command was not found. Please ensure it is installed and in your PATH.", file=sys.stderr)
        sys.exit(127) # Standard exit code for command not found
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
