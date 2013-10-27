Clustered Backup Server
=======================

This is a backup system that was developed by tummy.com and has been in use
since 2010.  We have deployed it among a number of our consulting clients,
handling backups of between 5 and 200 servers.  tummy-backup has proven
to be an extremely robust and reliable system over the years.

This is the result of being a veneer on top of existing, robust tools which
do the data replication, deduplication, and snapshotting: rsync and ZFS.
We have used it with both ZFS-fuse and (to a lesser extent) ZFS-on-Linux,
with good results.  It should work on any platform that has: rsync, ZFS,
Python, and Postgres.  We have used it primarily on Ubuntu Linux LTS, but
have also successfully deployed it on CentOS.
