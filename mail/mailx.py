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
                if ':' in item:
                    key, value = item.split(':', 1)
                    headers[key.strip()] = value.strip()
                else:
                    print(f"Warning: '{item}' is not a valid header format and file doesn't exist", file=sys.stderr)
        
        # Add explicit attachments from -A
        attachments.extend(args.attach_file)
        
        return attachments, headers
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
            hostname = socket.getfqdn()
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
        
        # Additional headers from -a option
        for header in args.attach:
            if ':' in header:
                key, value = header.split(':', 1)
                headers[key.strip()] = value.strip()
        
        return headers
    
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
            hostname = socket.getfqdn()
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
        
        # Add custom headers
        headers.update(custom_headers)
        
        return headers
    
    def create_mime_message(self, headers: Dict[str, str], body: str, attachments: List[str]) -> str:
        """Create MIME message with attachments"""
        if not attachments:
            # Simple text message
            return self.format_simple_message(headers, body)
        
        # Create multipart message
        msg = MIMEMultipart()
        
        # Set headers
        for key, value in headers.items():
            if key.lower() not in ['to', 'cc', 'bcc']:  # These are handled separately
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
                    attachment = MIMEText(file_data.decode('utf-8', errors='replace'), sub_type)
                else:
                    # Binary attachment
                    attachment = MIMEBase(main_type, sub_type)
                    attachment.set_payload(file_data)
                    encoders.encode_base64(attachment)
                
                # Set filename
                filename = os.path.basename(filepath)
                attachment.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{filename}"'
                )
                
                msg.attach(attachment)
                
                if self.verbose:
                    print(f"Attached: {filepath} ({content_type})", file=sys.stderr)
                    
            except Exception as e:
                print(f"Error attaching file '{filepath}': {e}", file=sys.stderr)
        
        return msg.as_string()
    
    def format_simple_message(self, headers: Dict[str, str], body: str) -> str:
        """Format the complete email message"""
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
        return recipients
    
    def send_mail(self, message: str, recipients: List[str], args: argparse.Namespace) -> bool:
        """Send mail using sendmail"""
        if not recipients:
            print("No recipients specified", file=sys.stderr)
            return False
        
        if not os.path.exists(self.sendmail_path):
            print(f"Sendmail not found at {self.sendmail_path}", file=sys.stderr)
            return False
        
        # Build sendmail command
        cmd = [self.sendmail_path]
        
        # Add sendmail options
        if args.verbose:
            cmd.append('-v')
        
        # Add recipients
        cmd.extend(recipients)
        
        if args.debug or args.verbose:
            print(f"Executing: {' '.join(cmd)}", file=sys.stderr)
            print("Message:", file=sys.stderr)
            print(message, file=sys.stderr)
            print("---", file=sys.stderr)
        
        try:
            # Send message to sendmail
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=message)
            
            if process.returncode != 0:
                print(f"Sendmail failed with exit code {process.returncode}", file=sys.stderr)
                if stderr:
                    print(f"Error: {stderr}", file=sys.stderr)
                return False
            
            if args.verbose and stdout:
                print(stdout)
            
            return True
            
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
        except SystemExit as e:
            return e.code if e.code is not None else 1
        
        # Set instance variables from args
        self.debug = args.debug
        self.verbose = args.verbose
        self.ignore_interrupts = args.ignore_interrupts
        self.no_network = args.no_network
        
        # Handle mailbox operations
        if args.file is not None or args.user is not None:
            return self.handle_mailbox_operations(args)
        
        # Check if we have recipients for sending mail
        if not args.recipients and not args.cc and not args.bcc:
            print("No recipients specified", file=sys.stderr)
            return 1
        
        # Read message body
        if sys.stdin.isatty():
            body = self.read_message_body(args.ignore_dot)
        else:
            # Read from stdin (pipe/redirect)
            body = sys.stdin.read()
        
        # Check for empty body
        if args.empty_start and not body.strip():
            if self.verbose:
                print("Empty message body, not sending (use -E to override)")
            return 0
        
        # Parse attachments and custom headers
        attachments, custom_headers = self.parse_attachments_and_headers(args)
        
        # Build headers
        headers = self.build_email_headers(args, custom_headers)
        
        # Get all recipients
        all_recipients = self.get_all_recipients(args)
        
        # Create message (with or without attachments)
        message = self.create_mime_message(headers, body, attachments)
        
        # Send the mail
        if self.send_mail(message, all_recipients, args):
            if self.verbose:
                print(f"Mail sent to: {', '.join(all_recipients)}")
            return 0
        else:
            return 1

def main():
    """Entry point for the script"""
    wrapper = MailxWrapper()
    return wrapper.run()

if __name__ == "__main__":
    sys.exit(main())
