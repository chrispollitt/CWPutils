#!/usr/bin/env python3
"""
BSD mailx Python wrapper using sendmail
A drop-in replacement for bsd-mailx that uses /usr/sbin/sendmail as backend
"""

import sys
import os
import argparse
import subprocess
import email.utils
import tempfile
import mimetypes
import base64
from datetime import datetime
from typing import List, Optional, Dict, Any
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

class MailxWrapper:
    def __init__(self):
        self.sendmail_path = "/usr/sbin/sendmail"
        self.debug = False
        self.verbose = False
        self.interactive = False
        self.ignore_interrupts = False
        self.no_network = False

    def parse_args(self) -> argparse.Namespace:
        """Parse command line arguments to mimic bsd-mailx"""
        parser = argparse.ArgumentParser(
            description="BSD mailx wrapper using sendmail",
            add_help=False  # We'll handle -h ourselves if needed
        )

        # Flags
        parser.add_argument('-d', '--debug', action='store_true',
                          help='Enable debug mode')
        parser.add_argument('-E', '--empty-start', action='store_true',
                          help='Do not send messages with empty body')
        parser.add_argument('-I', '--ignore-interrupts', action='store_true',
                          help='Ignore interrupt signals during input')
        parser.add_argument('-i', '--ignore-dot', action='store_true',
                          help='Ignore dots alone on lines')
        parser.add_argument('-n', '--no-init', action='store_true',
                          help='Do not read system mailrc file')
        parser.add_argument('-N', '--no-network', action='store_true',
                          help='Do not make network connections')
        parser.add_argument('-v', '--verbose', action='store_true',
                          help='Verbose mode')

        # Options with values
        parser.add_argument('-a', '--header', action='append', default=[],
                          help='Add header (format: "Header: value") or attach file')
        parser.add_argument('-A', '--attach-file', action='append', default=[],
                          help='Attach file')
        parser.add_argument('-b', '--bcc', action='append', default=[],
                          help='BCC recipient')
        parser.add_argument('-c', '--cc', action='append', default=[],
                          help='CC recipient')
        parser.add_argument('-r', '--from', dest='from_addr',
                          help='Set From address')
        parser.add_argument('-s', '--subject',
                          help='Subject line')
        parser.add_argument('-f', '--file',
                          help='Read from mailbox file')
        parser.add_argument('-u', '--user',
                          help='Read user\'s mailbox')

        # Positional arguments (recipients)
        parser.add_argument('recipients', nargs='*',
                          help='Recipient email addresses')

        # Handle -- separator
        if '--' in sys.argv:
            idx = sys.argv.index('--')
            sys.argv.pop(idx)

        return parser.parse_args()

    def read_message_body(self, ignore_dot: bool = False) -> str:
        """Read message body from stdin until EOF or single dot"""
        lines = []

        if sys.stdin.isatty():
            print("Enter message body (end with . on a line by itself or Ctrl+D):")

        try:
            while True:
                try:
                    line = input()
                    if not ignore_dot and line.strip() == '.':
                        break
                    lines.append(line)
                except EOFError:
                    break
        except KeyboardInterrupt:
            if not self.ignore_interrupts:
                print("\nInterrupted.")
                return ""

        return '\n'.join(lines)

    def parse_attachments_and_headers(self, args: argparse.Namespace) -> tuple[List[str], Dict[str, str]]:
        """Parse -a options to separate file attachments from headers"""
        attachments = []
        headers = {}

        for item in args.header:
            if ':' in item and not os.path.exists(item):
                # Looks like a header (contains : and is not a file)
                key, value = item.split(':', 1)
                headers[key.strip()] = value.strip()
            elif os.path.exists(item):
                # File exists, treat as attachment
                attachments.append(item)
            else:
                # Could be a header without : or non-existent file
                if ':' in item: # Try to parse as header if it contains a colon
                    key, value = item.split(':', 1)
                    headers[key.strip()] = value.strip()
                else:
                    # If it's not a file and doesn't look like a header, it might be an attachment that doesn't exist yet
                    # or an invalid header. For now, let's warn if verbose.
                    if self.verbose:
                        print(f"Warning: Item '{item}' from -a option is not an existing file and not a clear 'Header: value' format. Ignoring as header, will be treated as potential attachment if path is valid later.", file=sys.stderr)
                    # It could still be intended as an attachment, so add it. create_mime_message will check existence.
                    attachments.append(item)


        # Add explicit attachments from -A
        attachments.extend(args.attach_file)

        return attachments, headers

    def build_email_headers(self, args: argparse.Namespace, custom_headers: Dict[str, str]) -> Dict[str, str]:
        """Build email headers from arguments"""
        headers = {}

        # From header
        if args.from_addr:
            headers['From'] = args.from_addr
        else:
            # Default from current user and hostname
            import getpass
            import socket
            user = getpass.getuser()
            hostname = socket.getfqdn() # Fully Qualified Domain Name
            headers['From'] = f"{user}@{hostname}"

        # To header
        if args.recipients:
            headers['To'] = ', '.join(args.recipients)

        # CC header
        if args.cc:
            headers['Cc'] = ', '.join(args.cc)

        # Subject header
        if args.subject:
            headers['Subject'] = args.subject

        # Date header
        headers['Date'] = email.utils.formatdate(localtime=True)

        # Add custom headers from -a option (parsed in parse_attachments_and_headers)
        headers.update(custom_headers)

        # --- Add identifying X-Mailer header ---
        headers['X-Mailer'] = "mailx.py Python Sendmail Wrapper v1.0"
        # --- End of addition ---

        return headers

    def create_mime_message(self, headers: Dict[str, str], body: str, attachments: List[str]) -> str:
        """Create MIME message with attachments"""
        if not attachments:
            # Simple text message
            msg_obj = MIMEText(body, 'plain', 'utf-8')
            # Add headers to the message object directly for simple messages
            for key, value in headers.items():
                msg_obj[key] = value
            return msg_obj.as_string()

        # Create multipart message
        msg = MIMEMultipart()

        # Set headers
        for key, value in headers.items():
            # These headers are primarily for the envelope and are handled by sendmail,
            # but also good to have in the message itself.
            # For MIMEMultipart, some headers like To, Cc, Subject are conventionally set.
            msg[key] = value

        # Add text body
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Add attachments
        for filepath in attachments:
            if not os.path.exists(filepath):
                print(f"Warning: Attachment file '{filepath}' not found", file=sys.stderr)
                continue

            try:
                with open(filepath, 'rb') as f:
                    file_data = f.read()

                # Guess content type
                content_type, encoding = mimetypes.guess_type(filepath)
                if content_type is None or encoding is not None:
                    content_type = 'application/octet-stream'

                main_type, sub_type = content_type.split('/', 1)

                if main_type == 'text':
                    # Text attachment
                    attachment = MIMEText(file_data.decode('utf-8', errors='replace'), _subtype=sub_type)
                else:
                    # Binary attachment
                    attachment = MIMEBase(main_type, sub_type)
                    attachment.set_payload(file_data)
                    encoders.encode_base64(attachment)

                # Set filename
                filename = os.path.basename(filepath)
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=filename # Using the filename parameter is more robust
                )

                msg.attach(attachment)

                if self.verbose:
                    print(f"Attached: {filepath} ({content_type})", file=sys.stderr)

            except Exception as e:
                print(f"Error attaching file '{filepath}': {e}", file=sys.stderr)

        return msg.as_string()

    def format_simple_message(self, headers: Dict[str, str], body: str) -> str:
        """Format the complete email message (used if create_mime_message is bypassed for simple text)"""
        # This method might become less relevant if create_mime_message handles all cases.
        # However, keeping it for clarity if a non-MIME path was ever desired.
        # For now, create_mime_message handles simple text by creating a MIMEText object.
        message_lines = []

        # Add headers
        for key, value in headers.items():
            message_lines.append(f"{key}: {value}")

        # Empty line separating headers from body
        message_lines.append("")

        # Add body
        message_lines.append(body)

        return '\n'.join(message_lines)


    def get_all_recipients(self, args: argparse.Namespace) -> List[str]:
        """Get all recipients (To, CC, BCC)"""
        recipients = []
        recipients.extend(args.recipients)
        recipients.extend(args.cc)
        recipients.extend(args.bcc)
        return list(set(filter(None, recipients))) # Ensure uniqueness and remove empty strings

    def send_mail(self, message_string: str, recipients: List[str], args: argparse.Namespace) -> bool:
        """Send mail using sendmail"""
        if not recipients:
            print("No recipients specified", file=sys.stderr)
            return False

        if not os.path.exists(self.sendmail_path):
            print(f"Sendmail not found at {self.sendmail_path}", file=sys.stderr)
            return False

        # Build sendmail command
        cmd = [self.sendmail_path, "-i"] # -i to ignore dots on lines by themselves in message
        
        # Add sendmail options
        if args.verbose: # bsd-mailx -v maps to sendmail -v
            cmd.append('-v')
        if args.from_addr: # sendmail uses -f for envelope sender
             cmd.extend(['-f', args.from_addr])


        # Add recipients to the command line for sendmail
        cmd.extend(recipients)

        if args.debug or args.verbose:
            print(f"Executing: {' '.join(cmd)}", file=sys.stderr)
            print("Message being sent to sendmail stdin:", file=sys.stderr)
            print(message_string, file=sys.stderr)
            print("---", file=sys.stderr)

        try:
            # Send message to sendmail
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors='replace' # Handle potential encoding issues in the message
            )

            stdout, stderr = process.communicate(input=message_string)

            if process.returncode != 0:
                print(f"Sendmail failed with exit code {process.returncode}", file=sys.stderr)
                if stdout: # sendmail can output to stdout on error too
                    print(f"Sendmail stdout:\n{stdout}", file=sys.stderr)
                if stderr:
                    print(f"Sendmail stderr:\n{stderr}", file=sys.stderr)
                return False

            if args.verbose:
                if stdout:
                    print(f"Sendmail stdout:\n{stdout}", file=sys.stdout) # Verbose output to stdout
                if stderr: # sendmail -v often prints to stderr even on success
                    print(f"Sendmail stderr (verbose):\n{stderr}", file=sys.stderr)


            return True

        except FileNotFoundError:
            print(f"Error: The '{self.sendmail_path}' command was not found.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"Error executing sendmail: {e}", file=sys.stderr)
            return False

    def handle_mailbox_operations(self, args: argparse.Namespace) -> int:
        """Handle -f and -u options (mailbox reading operations)"""
        print("Mailbox reading operations (-f, -u) are not implemented in this wrapper.",
              file=sys.stderr)
        print("This wrapper only supports sending mail.", file=sys.stderr)
        return 1

    def run(self) -> int:
        """Main entry point"""
        try:
            args = self.parse_args()
        except SystemExit as e: # Catches parser.exit()
            return e.code if isinstance(e.code, int) else 1


        # Set instance variables from args
        self.debug = args.debug
        self.verbose = args.verbose
        self.ignore_interrupts = args.ignore_interrupts
        self.no_network = args.no_network # Currently not used, but kept for mailx compatibility

        # Handle mailbox operations
        if args.file is not None or args.user is not None:
            return self.handle_mailbox_operations(args)

        # Get all recipients for validation and sending
        all_recipients = self.get_all_recipients(args)
        if not all_recipients:
            # If -t is used in sendmail, recipients might be in headers, but this script
            # also needs them for the sendmail command line.
            # bsd-mailx requires recipients on command line or via To/Cc/Bcc in interactive mode.
            # For non-interactive, if no recipients on CLI, it's an error.
            print("No recipients specified (To, Cc, Bcc).", file=sys.stderr)
            # Mimic mailx exit code for "No recipients specified"
            # It's often 1, but can depend on specific mailx version/OS.
            # Using a generic error code.
            return 1 # EX_USAGE or similar often 64, but 1 is common for general errors.


        # Read message body
        body = ""
        if sys.stdin.isatty() and not args.subject and not any(header.lower().startswith("subject:") for header in args.header):
            # Interactive mode: prompt for subject if not given
            try:
                subject_line = input("Subject: ")
                if subject_line:
                    args.subject = subject_line # This will be used in build_email_headers
            except EOFError: # Ctrl+D on subject
                pass # No subject given
            except KeyboardInterrupt:
                if not self.ignore_interrupts:
                    print("\nInterrupted.")
                    return 130 # Standard exit code for Ctrl+C
                pass # Subject prompt interrupted, proceed without subject

        if sys.stdin.isatty(): # If still a TTY (even after subject prompt)
            if self.verbose:
                print("Reading message body from TTY. End with '.' on a line by itself or Ctrl+D.")
            body = self.read_message_body(args.ignore_dot)
            if body == "" and not self.ignore_interrupts and not sys.stdin.isatty(): # Check if interrupt occurred in read_message_body
                 # This check is a bit tricky, as read_message_body handles its own interrupt message.
                 # If body is empty and it was an interrupt, we might have already printed.
                 pass
        else:
            # Read from stdin (pipe/redirect)
            if self.verbose:
                print("Reading message body from stdin (pipe/redirect).", file=sys.stderr)
            body = sys.stdin.read()


        # Check for empty body
        if args.empty_start and not body.strip():
            if self.verbose:
                print("Empty message body, not sending (-E specified).", file=sys.stderr)
            return 0 # mailx exits 0 if -E is given and body is empty

        # Parse attachments and custom headers from -a
        attachments, custom_headers = self.parse_attachments_and_headers(args)

        # Build headers (now includes X-Mailer)
        headers = self.build_email_headers(args, custom_headers)

        # Create message (with or without attachments)
        # The create_mime_message now handles both simple and multipart.
        message_string = self.create_mime_message(headers, body, attachments)

        if self.debug:
            print("Constructed MIME Message:", file=sys.stderr)
            print(message_string, file=sys.stderr)
            print("---", file=sys.stderr)

        # Send the mail
        if self.send_mail(message_string, all_recipients, args):
            if self.verbose and not args.debug: # Avoid double printing if debug is also on
                # The actual sending success message is often part of sendmail's verbose output
                print(f"Mail sent to: {', '.join(all_recipients)} (via sendmail)", file=sys.stderr)
            return 0 # EX_OK
        else:
            # Error messages should have been printed by send_mail or earlier.
            return 1 # General error exit code

def main():
    """Entry point for the script"""
    wrapper = MailxWrapper()
    # Ensure that SystemExit exceptions from argparse or our own exit calls
    # are properly propagated to set the script's exit code.
    try:
        return wrapper.run()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except KeyboardInterrupt:
        print("\nOperation aborted by user (Ctrl+C).", file=sys.stderr)
        return 130 # Standard exit code for SIGINT
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        return 1 # General error

if __name__ == "__main__":
    sys.exit(main())