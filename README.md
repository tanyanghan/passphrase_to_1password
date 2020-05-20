# Extracting Phabricator Passphrase and importing into 1Password

For whatever reason, you may find yourself needing to extract the whole Phabricator Passphrase database and importing it into your 1Password.

For this, you will need to have:
1. SSH access to the server instance where your Phabricator is hosted
2. Access rights to be able to view Phabricator configuration files
3. With the above two, you can view the login information to the mysql database
4. mrc-converter-suite

## Proceed with caution, caveat emptor

Though the following steps are safe if you follow it exactly, you can do ***very bad things*** if you don't know what you are doing while logged into your Phabricator server instance or the mysql database.

I will take no responsibility if you wipe out your Phabricator server, mysql database, or you let your plain text password mysql dump file fall into the wrong hands while following these instructions. 

## mrc-converter-suite

You'll need to grab this 1Password community tool from: 

https://discussions.agilebits.com/discussion/30286/mrcs-convert-to-1password-utility-mrc-converter-suite

This tool is required because it allows custom fields to be added to your 1Password entry that you are importing.

Unzip the zipfile into the same directory as this Git checkout so that `mrc-converter-suite` is a directory under the Git repo.

You will need Perl available to use this tool, which I assume you do.

## Finding Phabrictor's settings file

The first thing is to find out your Phabricator's MySQL login information. You can easily do this by looking in the `local.json` configuration file for your Phabricator. This is usually found in the directory `/phabricator/conf/local/local.json`. 

The four fields in `local.json` you are interested in are:
```
    "mysql.host" - eg. mysql.abc.com
    "mysql.port" - eg. 3306
    "mysql.pass" - eg. my_p@ssw0rd
    "mysql.user" - eg. phabricator
```

## Extracting the databases from MySQL

Once you have the above information, you can use `mysqldump` to grab the two databases that you will need. The two databases you are interested in are:
1. phabricator_passphrase
2. phabricator_user

The user database is used to reference the full name of the Passphrase entry's Author, which we'll add to the 1Password entry so that we'll know who created the entry.

The commands for `mysqldump` are as follows, using the example values given above:
```
    mysqldump --user=phabricator --password --host mysql.abc.com --port 3306 phabricator_passphrase > phabricator_passphrase.sql
    mysqldump --user=phabricator --password --host mysql.abc.com --port 3306 phabricator_user > phabricator_user.sql
```

Be very careful with securing the file `phabricator_passphrase.sql`, as all the passwords in the file are not encrypted and anyone who gets a copy of the file will be able to read it like an open book.

Transfer these two `.sql` files to the same directory as this Git checkout. I used scp. 

## Converting Passphrase to 1Password using passphrase_to_1password.py

Finally, after all the above, you will be ready to use this Python script to do the conversion and output a `.1pif` file that can be imported into 1Password.

The most basic call you will need to do is:

```
    python3 passphrase_to_1password.py -p phabricator_passphrase.sql -u phabricator_user.sql
```

This will output two files named:
1. `output_<date and timestamp>.csv`
2. `output_<date and timestamp>.1pif`

The `.csv` file is an intermediate file that is fed to mrc-converter-suite and can be deleted. 

The `.1pif` file is the one you need to import into 1Password. 

If you are having problems, a couple useful options available to help are:
```
  -s, --save_intermediate_file
                        Flag to saves the intermediate data as json files (for
                        debug)
  -d {DEBUG,INFO,ERROR}, --debug_level {DEBUG,INFO,ERROR}
                        Select the debug level (default level INFO)
```

The `-s` flag will save the itermediate json files for inspection.

The `-d` option allows you to select `DEBUG` logging level for more information about the fields found for each table.

## What gets imported into 1Password

The following fields are imported into 1Password:
1. Title - The title will be the combined Passphrase index number, with `K` prepended to it, together with the `name` of the Passphrase entry.
2. Username
3. Password - This will depend on the `CredentialType` of the Passphrase entry, in my instance, there were five different types. More below.
4. Author - The name of the author of the Passphrase entry.
5. Created - This is the timestamp when the Passphrase entry was created. 
6. Modified - This is the last time anyone interacted with the Passphrase entry (including viewing the secret) 
7. Notes - This is the Description field in the Passphrase entry.
8. Creditial-type - This is the Passphrase entry's `CredentialType`, I only included the 5 types I found from my `mysqldump`. They are:
    1. note
    2. ssh-generated-key
    3. ssh-key-text
    4. token
    5. password

If the Credential-type is not `password`, then the imported 1Password entry's `password` field will be blank. Instead, an original field with the same name as the Credential-type will contain the secret. 

## Handling escape backslashes, double and single quotes

I have tried my best to correctly handle the escape backslashes, double and single quotes. I think I got it right, but if your import turns out looking wrong, let me know. 
