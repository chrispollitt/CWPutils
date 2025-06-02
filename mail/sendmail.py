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
# FromAddress = sender@example.com
# IgnoreDots = false

"""

import sys
import os
import argparse
import subprocess
import shlex
import configparser
import socket  # Added for hostname
from datetime import datetime  # Added for timestamp

# --- Default Configuration Values ---
DEFAULT_SSH_PORT = 22
DEFAULT_REMOTE_SENDMAIL_PATH = "/usr/sbin/sendmail"
DEFAULT_REMOTE_SENDMAIL_OPTIONS = "" # e.g., "-t -oi"
DEFAULT_VERBOSE = False
DEFAULT_FROM_ADDRESS = None # ADDED: Default for From Address
DEFAULT_IGNORE_DOTS = False # ADDED: Default for Ignore Dots

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
        try:
            cfg_to_update['ssh_port'] = ssh_section.getint('Port', cfg_to_update.get('ssh_port'))
        except ValueError:
            if cfg_to_update.get('verbose', DEFAULT_VERBOSE):
                print(f"Warning: Invalid Port value in config. Using {cfg_to_update.get('ssh_port')}.", file=sys.stderr)

        cfg_to_update['ssh_key_file'] = ssh_section.get('KeyFile', cfg_to_update.get('ssh_key_file'))
        cfg_to_update['remote_sendmail_path'] = ssh_section.get('RemoteSendmailPath', cfg_to_update.get('remote_sendmail_path'))
        cfg_to_update['remote_sendmail_options'] = ssh_section.get('RemoteSendmailOptions', cfg_to_update.get('remote_sendmail_options'))
        
        # ADDED: Load new config options
        cfg_to_update['from_address'] = ssh_section.get('FromAddress', cfg_to_update.get('from_address'))
        try:
            cfg_to_update['ignore_dots'] = ssh_section.getboolean('IgnoreDots', cfg_to_update.get('ignore_dots'))
        except ValueError:
            if cfg_to_update.get('verbose', DEFAULT_VERBOSE):
                print(f"Warning: Invalid IgnoreDots value in config. Using {cfg_to_update.get('ignore_dots')}.", file=sys.stderr)
        
        try:
            cfg_to_update['verbose'] = ssh_section.getboolean('Verbose', cfg_to_update.get('verbose'))
        except ValueError:
             if cfg_to_update.get('verbose', DEFAULT_VERBOSE):
                print(f"Warning: Invalid Verbose value in config. Using {cfg_to_update.get('verbose')}.", file=sys.stderr)


def get_env_var(var_name: str, default_value: any, type_conv=str):
    """Gets an environment variable with a prefix, applying type conversion."""
    env_val_str = os.getenv(f"{ENV_PREFIX}{var_name.upper()}") # MODIFIED: Ensure var_name is upper for env var
    if env_val_str is not None:
        try:
            # Special handling for boolean string conversion if type_conv is bool
            if type_conv == bool:
                if env_val_str.lower() in ('true', '1', 'yes', 'on'):
                    return True
                elif env_val_str.lower() in ('false', '0', 'no', 'off'):
                    return False
                else:
                    raise ValueError(f"Invalid boolean string: {env_val_str}")
            return type_conv(env_val_str)
        except ValueError as e:
            print(f"Warning: Invalid environment variable {ENV_PREFIX}{var_name.upper()}='{env_val_str}'. Error: {e}. Using default/config.", file=sys.stderr)
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
        'recipients': [],
        'from_address': DEFAULT_FROM_ADDRESS, # ADDED
        'ignore_dots': DEFAULT_IGNORE_DOTS,   # ADDED
    }

    # 2. Load configuration from files (updates config dict)
    load_config_from_files(config)

    # 3. Prepare argparse, using values from (Defaults -> Config Files -> Env) as defaults for CLI args
    parser = argparse.ArgumentParser(
        description="Forward email from stdin to remote sendmail via SSH.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Helper to get default for argparse, respecting ENV > Config > Hardcoded default
    def arg_default(env_key_suffix, config_key, type_conv=str):
        # For booleans where action='store_true', type_conv should handle string to bool
        if type_conv == bool:
             return get_env_var(env_key_suffix, config[config_key], type_conv=bool)
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
                        help="Options to pass to the remote sendmail command (e.g., '-oident=foo'). Note: some options like -f may be overridden by dedicated arguments.")
    
    # ADDED: New arguments for sendmail options
    parser.add_argument('-f', '--from-address', type=str,
                        default=arg_default('FROM_ADDRESS', 'from_address'),
                        help="Envelope sender address (passed as -f to remote sendmail). Overrides -f in --remote-sendmail-options.")
    parser.add_argument('-i', '--ignore-dots', action='store_true',
                        default=arg_default('IGNORE_DOTS', 'ignore_dots', type_conv=bool), # MODIFIED type_conv
                        help="Pass -i to remote sendmail (ignores dots on lines by themselves). Added if not in --remote-sendmail-options.")

    # Other Arguments
    # MODIFIED: Use arg_default for verbose as well for consistency
    verbose_cli_default = arg_default('VERBOSE', 'verbose', type_conv=bool)
    parser.add_argument('-v', '--verbose', action='store_true',
                        default=verbose_cli_default,
                        help="Enable verbose output for this script. Also passes -v to remote sendmail if not already specified in --remote-sendmail-options.")
    parser.add_argument('recipients', nargs='*',
                        help="Recipient email addresses. Usually not needed if '-t' is in remote_sendmail_options.")

    args = parser.parse_args()

    # 4. Final configuration is now in `args` object.

    # Validation
    if not args.ssh_host:
        parser.error("SSH host is required. Set via --ssh-host, environment, or config file.")
    if not args.ssh_user:
        parser.error("SSH user is required. Set via --ssh-user, environment, or config file.")

    remote_opts_str = args.remote_sendmail_options if args.remote_sendmail_options else ""
    
    # MODIFIED: Check for -t considers options that will be added later too.
    # For now, this validation remains based on the raw remote_opts_str and recipients.
    # A more sophisticated check would analyze the final command.
    temp_final_opts_check = list(shlex.split(remote_opts_str))
    if args.ignore_dots and '-i' not in temp_final_opts_check: temp_final_opts_check.append('-i')
    # -t is often used with recipients in the header, so this validation is key
    if '-t' not in temp_final_opts_check and not args.recipients:
        parser.error("Recipients must be provided on the command line if '-t' is not effectively part of the remote sendmail options (via --remote-sendmail-options or other flags that imply recipient handling).")


    # 5. Read the entire email message from stdin
    original_email_message = sys.stdin.read()

    # --- START: Add custom trace header ---
    try:
        hostname = socket.getfqdn()
        if not hostname or hostname == 'localhost': 
            hostname = socket.gethostname()
    except Exception:
        hostname = "unknown_host" 

    timestamp = datetime.now().isoformat()
    trace_header_value = f"Handled by sendmail.py on {hostname} at {timestamp} (forwarding to {args.ssh_user}@{args.ssh_host})"
    trace_header = f"X-SendmailPy-Trace: {trace_header_value}\n"
    email_message_to_send = trace_header + original_email_message
    # --- END: Add custom trace header ---

    # 6. Construct the SSH command
    ssh_command = ['ssh']
    ssh_command.extend(['-o', 'BatchMode=yes'])
    if args.ssh_port != DEFAULT_SSH_PORT:
        ssh_command.extend(['-p', str(args.ssh_port)])
    if args.ssh_key_file:
        ssh_command.extend(['-i', args.ssh_key_file])
    ssh_command.append(f"{args.ssh_user}@{args.ssh_host}")

    # --- MODIFIED: Construct the remote sendmail command string with new options ---
    remote_sendmail_cmd_parts = [shlex.quote(args.remote_sendmail_path)]
    
    options_from_remote_opts_str = []
    if remote_opts_str:
        options_from_remote_opts_str = shlex.split(remote_opts_str)

    # If --from-address is given, it takes precedence. Filter out any -f from options_from_remote_opts_str.
    final_remote_options = []
    if args.from_address:
        skip_next = False
        # Iterate through the options parsed from --remote-sendmail-options
        for i in range(len(options_from_remote_opts_str)):
            if skip_next:
                skip_next = False
                continue
            # If we find '-f', we skip it and its argument
            if options_from_remote_opts_str[i] == '-f':
                skip_next = True 
            else:
                # Otherwise, keep the option
                final_remote_options.append(options_from_remote_opts_str[i])
        # Add the -f and its value from the dedicated --from-address argument
        final_remote_options.extend(['-f', shlex.quote(args.from_address)])
    else:
        # If --from-address is not used, just use the options as they came from --remote-sendmail-options
        final_remote_options.extend(options_from_remote_opts_str)

    # Handle -i (ignore dots)
    # Add if args.ignore_dots is true and -i is not already in final_remote_options
    if args.ignore_dots and '-i' not in final_remote_options:
        final_remote_options.append('-i')
        
    # Handle -v (verbose for remote sendmail, triggered by this script's verbose flag)
    # Add if args.verbose is true (meaning sendmail.py is verbose) and -v is not already in final_remote_options
    #if args.verbose and '-v' not in final_remote_options:
    #    final_remote_options.append('-vv')
        
    # Add all processed options to the command
    remote_sendmail_cmd_parts.extend(final_remote_options)

    # Add recipients (these are positional arguments to sendmail)
    if args.recipients:
        remote_sendmail_cmd_parts.extend([shlex.quote(rcpt) for rcpt in args.recipients])
    # --- END MODIFIED section for remote sendmail command construction ---

    full_remote_command = ' '.join(remote_sendmail_cmd_parts)
    ssh_command.append(full_remote_command)

    if args.verbose:
        print(f"Info: Adding trace header: X-SendmailPy-Trace: {trace_header_value}", file=sys.stderr)
        print(f"Info: Attempting to send email via: {' '.join(map(shlex.quote, ssh_command))}", file=sys.stderr) # MODIFIED: quote for safety
        print(f"Info: Remote sendmail command to be executed: {full_remote_command}", file=sys.stderr)
        if len(email_message_to_send) > 500:
            print(f"Info: Email message to send (first 500 chars with added header):\n{email_message_to_send[:500]}...", file=sys.stderr)
        else:
            print(f"Info: Email message to send (with added header):\n{email_message_to_send}", file=sys.stderr)
        print("---", file=sys.stderr)

    # 7. Execute the command
    try:
        process = subprocess.Popen(
            ssh_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='replace'
        )
        stdout, stderr = process.communicate(input=email_message_to_send)

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
            if stderr: 
                print(f"Stderr:\n{stderr}", file=sys.stderr)
        sys.exit(0)

    except FileNotFoundError:
        print(f"Error: The 'ssh' command was not found. Please ensure it is installed and in your PATH.", file=sys.stderr)
        sys.exit(127)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()