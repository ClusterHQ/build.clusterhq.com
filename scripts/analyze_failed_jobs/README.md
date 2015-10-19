This is a simple Ansible playbook to download and parse the Buildbot tasks' log.

# Running the playbook

Clone this repository on your local machine. And then run:
```
sudo pip install buildbot
sudo pip install ansible
ssh-add [buildbot_server_key]
ansible-playbook playbook.yml
```

This will download and parse the log files. Generating a CSV file `out/test-count.csv`. The file contains three columns: builder, test and number of failures.