import logging, argparse, re, sys, traceback, csv, copy, json, os, time
from subprocess import call

# defines
SINGLE_QUOTE_PLACEHOLDER = "@SINGLE_placeholder"
DOUBLE_QUOTE_PLACEHOLDER = "@DOUBLE_placeholder"

# list of fields in the CSV output file, we use it to validate the added field names in the login class
csv_fields = ["Title","Login URL","Login Username","Login Password","Created","Modified",
              "Author","Notes","credential-type","note","ssh-generated-key","ssh-key-text","token"]

def parseOptions():
    parser = argparse.ArgumentParser(description="Imports sql dump from Phabricator to extract passphrase for importing into 1Password")

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

def load_table(sql_filename, table_name, index_column=None):
    if index_column:
        #if we specify an index column, we want a dictionary
        data = {}
    else:
        #if not, we just make a list
        data = []
    try:
        with open(sql_filename, "r") as f:
            tableFound = False
            table_fields = []
            table_fields_end = False
            for line in f:
                if not tableFound:
                    matchObj = re.match('CREATE TABLE `('+table_name+')`',line)
                    if matchObj:
                        tableFound = True
                        logging.info("Table found: %s"%matchObj.group(1))
                else:
                    if not table_fields_end:
                        matchObj = re.match('\A +`(\w+)`', line)
                        if matchObj:
                            table_fields.append(matchObj.group(1))
                            logging.debug("Field found: %s"%matchObj.group())
                        else:
                            matchObj = re.match('\A\)',line)
                            if matchObj:
                                table_fields_end = True
                    else:
                        matchObj = re.match('INSERT INTO `'+table_name+'` VALUES (.+)', line)
                        if matchObj:
                            table_values = matchObj.group(1).lstrip('(').rstrip(';)').replace('),(','\n').replace("	","    ")
                            # replace /' with SINGLE_QUOTE_PLACEHOLDER but not //'
                            table_values = re.sub(r"([^\\])(\\')",r"\1"+SINGLE_QUOTE_PLACEHOLDER,table_values)
                            # replace /" with DOUBLE_QUOTE_PLACEHOLDERe but not //"
                            table_values = re.sub(r'([^\\])(\\")',r"\1"+DOUBLE_QUOTE_PLACEHOLDER,table_values)
                            value_reader = csv.reader(table_values.splitlines(), quotechar="'", quoting=csv.QUOTE_MINIMAL)
                            for row in value_reader:
                                count = 0
                                new_dict = {}
                                for column in row:
                                    try:
                                        #new_dict[table_fields[count]] = column.replace("@han_single_quote","'").replace("@han_double_quote","\"")
                                        new_dict[table_fields[count]] = column
                                    except IndexError as e:
                                        logging.error(row)
                                        raise
                                    count+=1
                                if index_column:
                                    data[new_dict[index_column]] = copy.deepcopy(new_dict)
                                else:
                                    data.append(copy.deepcopy(new_dict))
                            break                     
            f.close()
    except IOError:
        logging.error("Failed to read file %s" % sql_filename)
        raise
    except:
        logging.error("Unexpected error: %s" % sys.exc_info()[0])
        logging.error(traceback.format_exc())
        raise

    return data

class login():
    # mainly, this class was created so we can cross-check that any field names
    # added to the entry are in the required_cvs_fields list. It is to prevent
    # me adding a new field name, but forget to update the cvs_fields list that
    # is passed to csv.dictWriter
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