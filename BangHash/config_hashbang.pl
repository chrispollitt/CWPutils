#!/usr/bin/env perl

use File::Slurper qw~read_lines write_text~;

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
#  tcl     => [ 'tclsh'     , '<<< "puts [info patchlevel]"' ],
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

# which -a
sub which_a {
  my $cmd = shift or die "Usage: which_a(command)\n";
  my @paths = split /:/, $ENV{PATH};
  my @results;
    foreach my $path (@paths) {
      my $full_path = "$path/$cmd";
      if (-x $full_path) {
          push @results, $full_path;
      }
  }
  return @results;
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
	# get list of files from command line
  my @files = @ARGV;
	# loop over files
  for my $file (@files) {
		my($ext, $hbang, $ohbang, @locs, $verflag, $ver, %vers, $eol, $ehbang);
		# see if file exists
		if(! -f $file) {
      warn "Unable to find file: $file\n";
      next;
		}
		# get extension
    $ext = ($file =~ /\.(\w+)$/)[0] or $ext = '';
		# get hasnbang
		my @script = read_lines($file);
    $ohbang = $script[0];
		$hbang = $ohbang;
		$eol = "\n";
    $hbang =~ m~^#!/?(?:[^/]+/){0,}(?:env\s+)?(\w+)(\s+.*)?$~;
		($hbang, $ehbang) = ($1 || '', $2 || '');
		if(! $hbang) {
			if($ext) {
				if(exists $exts{$ext}) {
		      $hbang = $exts{$ext}->[0];
				} else {
				  warn "Unknown ext for file: $file - '$ext'\n";
				  next;
				}
			} else {
				warn "Unable to determine script type: $file\n";
				next;
			}
		}
		# debug out
    warn "DEBUG: f=$file e=$ext h=$hbang\n" if($debug);
		# look for interpreter in PATH
    @locs = which_a($hbang);
		if(!@locs) {
				warn "Unable to locate interpreter in the PATH: $file\n";
				next;
		}
		# get ext if not there
		if(! $ext) {
			if(exists $hbangs{$hbang}) {
   		  $ext = $hbangs{$hbang};
			} else {
				warn "Unknown hbang in file: $file - '$hbang'\n";
				next;
			}
		}
		# look for ext in hash
		if(exists $exts{$ext}) {
		  $verflag = $exts{$ext}->[1];
		} else {
			warn "Unknown ext for file: $file - '$ext'\n";
			next;
		}
		# one or many?
		my $choice;
		if (@locs == 1) {
			$choice = $locs[0];	
		} else {
		  # loop over locations
		  for my $loc (@locs) {
		  	$loc =~ s~[\r\n]+$~~;
				# get version
		  	$ver = (grep(/\d\.\d/, `"$loc" $verflag 2>/dev/null`))[0] or $ver = '';
		  	$ver =~ s~^.*?(\d(?:\.\d+)+).*[\r\n]+$~$1~ or $ver = 'UNKNOWN';
        warn "DEBUG:   l=$loc v=$ver\n" if($debug);
		  	next if($ver eq 'UNKNOWN');
		  	$vers{$ver} = $loc;
		  }
		  # sort and loop over versions found
		  my @vers = sort_versions(keys %vers);
		  for my $ver (@vers) {
		  	warn "DEBUG: $vers{$ver} = $ver\n" if($debug);
		  }
		  # chose most recent version
		  $choice = $vers[-1];
		  $choice = $vers{$choice};
		}
		# fix hbang line
		$hbang = "#!" . $choice . $ehbang;
		if($ohbang =~ m~^#!~) {
			$script[0] = $hbang;
		} else {
			unshift(@script, $hbang)
		}
		write_text($file, join($eol, @script) . $eol);
		print "f=$file i=$choice\n";
  }
}

main();

__END__

==== CYGWIN ======================
PATH="$PATH:/cygdrive/d/Apps/Go/bin:/cygdrive/c/Program Files/PowerShell/7"

