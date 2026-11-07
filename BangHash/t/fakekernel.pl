#!/usr/bin/perl
# fakekernel.pl MODE SCRIPT [ARGS...]
#   (The full tool is now ../shebanglab; this small shim is what test_configure.sh uses.)
#
# Pretend to be the kernel's #! handler: read the first line of SCRIPT,
#   "#!/path/to/interpreter  args-string"
# and exec the interpreter the way a given kind of kernel would.
#
#   linux   : argv = interp, "args-string", script, ARGS      (KERNEL_SPLIT 0)
#   naive   : args-string split on whitespace only; backslashes
#             and quotes are NOT honoured                      (KERNEL_SPLIT 1)
#   perfect : args-string split like a shell: backslashes and
#             quotes honoured                                  (KERNEL_SPLIT 2)
#   solaris : only the first word of args-string is passed on;
#             the rest is dropped                              (KERNEL_SPLIT 1)
#
# Then argv = interp, <split args>..., script, ARGS
#
# Use: lets us test env2 against each kind of kernel on a machine that only
# has one.  Build env2 with the matching KERNEL_SPLIT (linux -> 0;
# naive or perfect -> 1; configure maps a perfect kernel to 1 too).
use strict; use warnings;
use Text::ParseWords qw(shellwords);

my ($mode, $script, @user) = @ARGV;
die "usage: $0 linux|naive|perfect|solaris script [args]\n" unless defined $script;

open(my $fh, '<', $script) or die "$script: $!\n";
my $line = <$fh>; close $fh;
chomp $line;
$line =~ s/^#!\s*// or die "$script: no #! line\n";
my ($interp, $rest) = split(/\s+/, $line, 2);
$rest = '' unless defined $rest;

my @args;
if    ($mode eq 'linux')   { @args = length($rest) ? ($rest) : () }
elsif ($mode eq 'naive')   { @args = split(' ', $rest) }
elsif ($mode eq 'perfect') { @args = shellwords($rest) }
elsif ($mode eq 'solaris') { my @w = split(' ', $rest); @args = @w ? ($w[0]) : () }
else { die "unknown mode '$mode'\n" }

exec { $interp } $interp, @args, $script, @user or die "exec $interp: $!\n";
