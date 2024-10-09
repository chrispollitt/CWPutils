#!/usr/bin/env perl

use strict;
use warnings;

# ext           hbang        ver  
our %exts = (
  awk     => [ 'awk'       , '--version' ],
  clj     => [ 'clojure'   , '--version' ],
  erl     => [ 'erlang'    , '--version' ],
  ex      => [ 'elixir'    , '--version' ],
  fish    => [ 'fish'      , '--version' ],
  go      => [ 'go'        , 'version'   ],
  groovy  => [ 'groovy'    , '--version' ],
  hs      => [ 'haskell'   , '--version' ],
  js      => [ 'node'      , '--version' ],
  kts     => [ 'kotlin'    , '--version' ],
  lua     => [ 'lua'       , '-v'        ],
  m       => [ 'MATLAB'    , '--version' ],
  php     => [ 'php'       , '--version' ],
  pl      => [ 'perl'      , '--version' ],
  ps1     => [ 'pwsh'      , '--version' ],
  py      => [ 'python3'   , '--version' ],
  R       => [ 'Rscript'   , '--version' ],
  raku    => [ 'raku'      , '--version' ],
  rb      => [ 'ruby'      , '--version' ],
  scala   => [ 'scala'     , '--version' ],
  scm     => [ 'scheme'    , '--version' ],
  sed     => [ 'sed'       , '--version' ],
  sh      => [ 'bash'      , '--version' ],
  st      => [ 'smalltalk' , '--version' ],
  swift   => [ 'swift'     , '--version' ],
  tcl     => [ 'tclsh'     , '<<< "puts [info patchlevel]"' ],
  zsh     => [ 'zsh'       , '--version' ],
);
our %hbangs = swap_hash( %exts );

# Set debug flag
our $debug = 0;
# Disable buffering
$| = 1;
select(STDERR); $| = 1; select(STDOUT);

# swap hash
sub swap_hash {
  my %original_hash = @_;
  my %swapped_hash;
  
  while (my ($key, $value) = each %original_hash) {
    $swapped_hash{$value->[0]} = $key;
  }
  
  return %swapped_hash;
}

# sort ver numbers
sub sort_versions {
    my @versions = @_;
    my @sorted = sort {
        my @a_parts = split /\./, $a;
        my @b_parts = split /\./, $b;
        
        # Remove any non-numeric characters from the parts
        @a_parts = map { s/\D.*//r } @a_parts;
        @b_parts = map { s/\D.*//r } @b_parts;
        
        # Ensure each version has exactly 3 parts by padding with zeros
        push @a_parts, 0 while @a_parts < 3;
        push @b_parts, 0 while @b_parts < 3;
        
				# do the compare
        $a_parts[0] <=> $b_parts[0] ||
        $a_parts[1] <=> $b_parts[1] ||
        $a_parts[2] <=> $b_parts[2]
    } @versions;
		return @sorted;
}

# main sub
sub main {
  my @files = @ARGV;
  for my $file (@files) {
		my($ext, $hbang, @locs, $verflag, $ver, %vers);
		if(! -f $file) {
      print STDERR "Unable to find file: $file\n";
      next;
		}
    $ext   = ($file =~ /\.(\w+)$/)[0] or $ext = '';
    $hbang = (`head -1 "$file"`)[0];
    $hbang =~ s~^#!/?(?:[^/]+/){0,}(?:env\s+)?(\w+)($|\s+.*)[\r\n]+$~$1~ or $hbang = '';
		if(! $hbang) {
			if($ext) {
				if(exists $exts{$ext}) {
		      $hbang = $exts{$ext}->[0];
				} else {
				  print STDERR "Unknown ext for file: $file - '$ext'\n";
				  next;
				}
			} else {
				print STDERR "Unable to determine script type: $file\n";
				next;
			}
		}
    print STDERR "DEBUG: f=$file e=$ext h=$hbang\n" if($debug);
    @locs   = (`which -a "$hbang" 2>/dev/null`);
		if(!@locs) {
				print STDERR "Unable to locate interpreter in the PATH: $file\n";
				next;
		}
		if(! $ext) {
			if(exists $hbangs{$hbang}) {
   		  $ext = $hbangs{$hbang};
			} else {
				print STDERR "Unknown hbang in file: $file - '$hbang'\n";
				next;
			}
		}
		if(exists $exts{$ext}) {
		  $verflag = $exts{$ext}->[1];
		} else {
			print STDERR "Unknown ext for file: $file - '$ext'\n";
			next;
		}
		for my $loc (@locs) {
			$loc =~ s~[\r\n]+$~~;
			$ver = (grep(/\d\.\d/, `"$loc" $verflag 2>/dev/null`))[0] or $ver = '';
			$ver =~ s~^.*?(\d(?:\.\d+)+).*[\r\n]+$~$1~ or $ver = 'UNKNOWN';
      print STDERR "DEBUG:   l=$loc v=$ver\n" if($debug);
			$vers{$ver} = $loc;
		}
		for my $ver (sort_versions(keys %vers)) {
			print "$vers{$ver} = $ver\n";
		}
  }
}

main();

__END__

`perl -lpi~ -e 's~x~x~ if($. == 1)' "$file"`;

==== CYGWIN ======================

PATH="$PATH:/cygdrive/d/Apps/Go/bin:/cygdrive/c/Program Files/PowerShell/7"

l=/bin/awk v=5.1.0
l=/bin/bash v=4.4.12
l=/bin/lua v=5.3.6
l=/bin/perl v=5.32.1
l=/bin/php v=7.3.7
l=/bin/python3 v=3.8.10
l=/bin/ruby v=2.6.4
l=/bin/sed v=4.4
l=/bin/tclsh v=8.6.11
l=/bin/zsh v=5.8
l=/cygdrive/c/Program Files/nodejs/node v=0.2.0
l=/cygdrive/c/Program Files/PowerShell/7/pwsh v=7.2.23
l=/cygdrive/c/Windows/system32/bash v=5.0.17
l=/cygdrive/d/Apps/Go/bin/go v=1.11.5

  clojure
  ex
* fish  
* groovy
  hs
  kts
  R
  scala
  scm
  swift

==== INTERMITTENT BUG !!!

$../config_hashbang.pl f_pl
DEBUG: f=f_pl e= h=perl
Unknown hbang in file: f_pl - 'perl'

$../config_hashbang.pl f_pl
DEBUG: f=f_pl e= h=perl
DEBUG:   l=/bin/perl v=5.32.1
