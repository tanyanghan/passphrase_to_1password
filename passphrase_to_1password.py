import logging, argparse, re, sys, traceback, csv, copy, json, os, time
from subprocess import call

# defines
SINGLE_QUOTE_PLACEHOLDER = "@SINGLE_placeholder"
DOUBLE_QUOTE_PLACEHOLDER = "@DOUBLE_placeholder"

# list of fields in the CSV output file, we use it to validate the added field
# names in the login class
csv_fields = ["Title","Login URL","Login Username",
              "Login Password","Created","Modified",
              "Author","Notes","credential-type","note",
              "ssh-generated-key","ssh-key-text","token"]

def parseOptions():
    parser = argparse.ArgumentParser(description="Imports mysqldump from Phabricator to extract passphrase for importing into 1Password")

    parser.add_argument("-p", "--passphrase_sql_file", 
        help="The passphrase SQL file",
        action="store", required=True)

    parser.add_argument("-u", "--user_sql_file", 
        help="The user SQL file",
        action="store", required=True)

    parser.add_argument("-o", "--output_file", 
        help="The output filename (the extension .csv and .1pif will be automatically added",
        action="store", required=False, default='output'+time.strftime('_%Y%m%d-%H%M',time.localtime()))

    parser.add_argument("-s", "--save_intermediate_file", 
        default=False, action="store_true" , help="Flag to saves the intermediate data as json files (for debug)")

    parser.add_argument("-d", "--debug_level", 
        help="Select the debug level (default level INFO)",
        action="store", required=False, default="INFO",
        choices=["DEBUG","INFO","ERROR"])

    args = parser.parse_args()

    return args

# load_table looks for an SQL table in the SQL file and loads the data into a
# list of dictionaries (one dictionary per line) if the index_column is not
# given. If the index_column is given, then it will return a dictionary of
# dictionaries with the corresponding index_column value as the key to each
# line.
def load_table(sql_filename, table_name, index_column=None):
    STATE_LOOK_FOR_TABLE = 0
    STATE_LOOK_FOR_FIELDS = 1
    STATE_LOOK_FOR_DATA = 2
    STATE_COMPLETE = 3
    state = STATE_LOOK_FOR_TABLE

    if index_column:
        #if we specify an index column, we want a dictionary
        data = {}
    else:
        #if not, we just make a list
        data = []
    try:
        with open(sql_filename, "r") as f:

            table_fields = []

            # loop through the SQL file with a little state machine that looks
            # for the create table statement, then detects every field in the
            # table, and finally, it looks for the insert statement for the
            # table and grabs all the data into dictionary for each line of 
            # data.  
            for line in f:
                # first thing is try to find the table
                if state == STATE_LOOK_FOR_TABLE:
                    matchObj = re.match('CREATE TABLE `('+table_name+')`',line)
                    if matchObj:
                        # we have found the table we were looking for
                        state += 1
                        logging.info("Table found: %s"%matchObj.group(1))
                elif state == STATE_LOOK_FOR_FIELDS:
                    # after find the table, we need to check if we have all the
                    # fields in the table recorded
                    matchObj = re.match(r'\A +`(\w+)`', line)
                    if matchObj:
                        # found a table field, append it to the
                        # table_fields list
                        table_fields.append(matchObj.group(1))
                        logging.debug("Field found: %s"%matchObj.group())
                    else:
                        # check if we found the end of the fields in the
                        # CREATE TABLE statement
                        matchObj = re.match(r'\A\)',line)
                        if matchObj:
                            # yes, we found the end of the fields, so move to
                            # next state
                            state += 1
                elif state == STATE_LOOK_FOR_DATA:
                    matchObj = re.match(r'INSERT INTO `'+table_name+'` VALUES (.+)', line)
                    if matchObj:
                        # we found the INSERT INTO statement for this table, 
                        # strip off first and last brackets and the semicolon
                        # Also, find any tab characters and just replace them 
                        # with four spaces. We split each item into its own
                        # line, so that we can use csv.DictReader to consume
                        # the whole thing for us.
                        table_values = matchObj.group(1).lstrip('(').rstrip(';)').replace('),(','\n').replace("	","    ")
                        # replace /' with SINGLE_QUOTE_PLACEHOLDER but not //'
                        table_values = re.sub(r"([^\\])(\\')",r"\1"+SINGLE_QUOTE_PLACEHOLDER,table_values)
                        # replace /" with DOUBLE_QUOTE_PLACEHOLDERe but not //"
                        table_values = re.sub(r'([^\\])(\\")',r"\1"+DOUBLE_QUOTE_PLACEHOLDER,table_values)

                        reader = csv.DictReader(table_values.splitlines(), fieldnames=table_fields, quotechar="'", quoting=csv.QUOTE_MINIMAL)
                        for row in reader:
                            if index_column:
                                data[row[index_column]] = copy.deepcopy(row)
                            else:
                                data.append(copy.deepcopy(row))
    
                        # we have reached the end of the data import for this table
                        state += 1
                        break
            f.close()
    except IOError:
        logging.error("Failed to read file %s" % sql_filename)
        raise
    except:
        logging.error("Unexpected error: %s" % sys.exc_info()[0])
        logging.error(traceback.format_exc())
        raise

    if state < STATE_COMPLETE:
        if state == STATE_LOOK_FOR_TABLE:
            sys.exit("Table '%s' not found in %s."%(table_name,sql_filename))
        elif state ==  STATE_LOOK_FOR_FIELDS:
            sys.exit("Something went wrong, I couldn't find the end of the fields for table '%s' in %s."%(table_name, sql_filename))
        elif state == STATE_LOOK_FOR_DATA:
            sys.exit("We couldn't load the data for table '%s' in %s."%(table_name, sql_filename))

    return data

class login():
    # mainly, this class was created so we can cross-check that any field names
    # added to the entry are in the required_cvs_fields list. It is to prevent
    # me adding a new field name, but forgetting to update the cvs_fields list
    # that is passed to csv.DictWriter
    def __init__(self, required_cvs_fields=[]):
        self.required_cvs_fields = required_cvs_fields

    def new(self):
        self.current_entry_dict = {
            "Login Username":"",
            "Login Password":"",
            "Login URL"     :""
        }

    def add(self, field_name, value):
        if field_name not in self.required_cvs_fields:
            raise AttributeError("The field_name '%s' is not in the required_cvs_fields list: %s"%(field_name,self.required_cvs_fields))
        
        self.current_entry_dict[field_name] = value

    def get(self):
        return copy.deepcopy(self.current_entry_dict)

def assemble_data(user_data, passphrase_data, secret_data):
    # assemble the data ready for output to csv
    # for 1Password login items using mrc-converter-suite, the fields are: 
    # Title,Login URL,Login Username,Login Password,Notes,Created,Modified
    # We add custom fields: Author,credential-type,note,ssh-generated-key,ssh-key-text,token
    assembled_dict = []

    login_entry = login(csv_fields)

    for entry in passphrase_data:
        login_entry.new()

        login_entry.add("Title","K" + entry["id"] + " - " + entry["name"])
        login_entry.add("Created",int(entry["dateCreated"]))
        login_entry.add("Modified",int(entry["dateModified"]))

        if entry["username"]:
            login_entry.add("Login Username",entry["username"])
        if entry["authorPHID"]:
            login_entry.add("Author",user_data[entry["authorPHID"]]["realName"])
        if entry["description"]:
            login_entry.add("Notes",entry["description"])

        # There are five "credentialType":
        # "note","password","ssh-generated-key","ssh-key-text","token",
        login_entry.add("credential-type",entry["credentialType"])
        if entry["credentialType"] == "password":
            try:
                login_entry.add("Login Password",secret_data[entry["secretID"]]["secretData"])
            except KeyError:
                # some times, secretID can be "NULL", so we just save "NULL" as the password
                login_entry.add("Login Password",entry["secretID"])
        else:
            try:
                login_entry.add(entry["credentialType"],secret_data[entry["secretID"]]["secretData"])
            except KeyError:
                # some times, secretID can be "NULL", so we just save "NULL" as the password
                login_entry.add(entry["credentialType"],entry["secretID"])

        assembled_dict.append(login_entry.get())

    return assembled_dict

if __name__ == "__main__":
    args = parseOptions()

    if args.debug_level == "DEBUG":
        logging_level = logging.DEBUG
    elif args.debug_level == "INFO":
        logging_level = logging.INFO
    elif args.debug_level == "ERROR":
        logging_level = logging.ERROR

    # set up basic logging
    logging.basicConfig(level=logging_level, format='%(asctime)s %(funcName)15s %(levelname)8s: %(message)s')

    # set up the output filenames and paths
    current_dir = os.path.dirname(os.path.realpath(__file__))
    output_csv_file = args.output_file+".csv"
    output_1pif_file = os.path.join(current_dir,args.output_file+".1pif")

    try:
        user_data = load_table(args.user_sql_file, 'user', 'phid')
        passphrase_data = load_table(args.passphrase_sql_file, 'passphrase_credential')
        secret_data = load_table(args.passphrase_sql_file, 'passphrase_secret', 'id')

        assembled_dict = assemble_data(user_data, passphrase_data, secret_data)

        if args.save_intermediate_file:
            logging.info("Saving intermediate files.")
            with open("user_data.json",'w') as f:
                json.dump(user_data, f, indent=4)
            with open("passphrase_data.json",'w') as f:
                json.dump(passphrase_data, f, indent=4)
            with open("secret_data.json",'w') as f:
                json.dump(secret_data, f, indent=4)
            with open("assembled_dict.json",'w') as f:
                json.dump(assembled_dict, f, indent=4)

        try:
            logging.info("Writing to %s."%output_csv_file)
            with open(output_csv_file, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile,csv_fields, extrasaction='ignore',dialect='excel')
                writer.writeheader()
                for entry in assembled_dict:
                    writer.writerow(entry)
        except IOError:
            logging.error("Failed to read file %s" % sql_filename)
            raise
        except:
            logging.error("Unexpected error: %s" % sys.exc_info()[0])
            logging.error(traceback.format_exc())
            raise
        else:
            logging.info("Writing complete %s."%output_csv_file)

        logging.info("Calling mrc-converter-suite.")
        if call(["perl","convert.pl","csv","-a",os.path.join("..",output_csv_file),"-o",output_1pif_file],cwd=os.path.join(current_dir,"mrc-converter-suite")) == 0:
            try:
                logging.info("mrc-converter-suite complete, fixing up escape backslashes, single and double quotes")
                with open(output_1pif_file, 'r') as f:
                    filedata = f.read()
                filedata = filedata.replace(SINGLE_QUOTE_PLACEHOLDER, "'")
                filedata = filedata.replace(DOUBLE_QUOTE_PLACEHOLDER, '\\"')
                filedata = filedata.replace('\\\\','\\')
                with open(output_1pif_file, 'w') as f:
                    f.write(filedata)
            except IOError:
                logging.error("Failed to read file %s" % sql_filename)
                raise
            except:
                logging.error("Unexpected error: %s" % sys.exc_info()[0])
                logging.error(traceback.format_exc())
                raise
            else:
                logging.info("Fix up complete. Output file: %s"%output_1pif_file)
        else:
            logging.error("mrc-converter-suite failed")
    except Exception as err:
        logging.exception("Unexpected Exception: {0}".format(err))
    except KeyboardInterrupt as e:
        logging.error("KeyboardInterrupt %s"%e)
        sys.exit("KeyboardInterrupt")
    except SystemExit as e:
        # must use logging error here to actually print out to the console
        logging.error("SystemExit: %s"%e)