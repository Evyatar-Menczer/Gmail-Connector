import pickle
import os.path
import json
import inspect
import threading
import logzero
from logzero import logger
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dateutil import parser

class DateUidException(Exception):
    pass

class GmailConnector:

    SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
    logzero.logfile("C:\\Users\\evya2\\PycharmProjects\\Recovery\\logs\\log.txt")

    def __init__(self, config_file=None):
        self.creds = None
        self.path = "."
        self.interval = 10

        if config_file is not None:
            self.init_with_config_file(config_file)

    def init_with_config_file(self, file):
        """Initializes the connector values - creds,path,interval(from the file)
         in case config file is given.

      Args:
        file: string, file's name

      Returns:
        None.
      """
        with open('config.json') as config_file:
            data = json.load(config_file)
        for key,val in data.items():
            if key.lower() == "credentials":
                self.creds = val
            elif key == "path":
                self.path = val
            elif key == "interval":
                self.interval = val

    def fulldate_to_time(self, date: str) -> str:
        """Converts full date string to time only, in format H-M-S.

      For example, converting 'Fri, 14 Aug 2020 00:10:55 +0300' -> "00-10-55"

      Args:
        date: the full date string.

      Returns:
        string time format H-M-S.
      """
        try:
            date_time = parser.parse(date)
            time_str = date_time.strftime("%H-%M-%S")
        except (Exception,SyntaxError) as e:
            logger.exception(f"Error in {inspect.currentframe().f_code.co_name}.\n" ,e)
            return None
        return time_str

    def extract_uuid(self, uuid):
        """Converts full uuid to a valid file name(remove invalid characters - \/:*?"<>| ).

    For exmaple,'<CAFyznE0J9meRG9mFdqwg9OnVYwATbcLeNAEJwvZb_=aQcPJq2w@mail.gmail.com>' ->

                'CAFyznE0J9meRG9mFdqwg9OnVYwATbcLeNAEJwvZb_=aQcPJq2w'

      Args:
        uuid: string, the full uuid as taken from the message.

      Returns:
        valid uuid for file's name.
      """
        try:
            fixed = uuid.split("@")[0]
            to_replace = '\/:*?"<>|'
            for char in to_replace:
                if char in fixed:
                    fixed = fixed.replace(char, "")
        except (EnvironmentError,AttributeError) as e:
            logger.excpetion(f"Error at {inspect.currentframe().f_code.co_name}.\n" , e)
            return None
        return fixed

    def save_messages(self, msgs_details):
        """Save all messages as .json file in format SENDER,RECIEVER,SUBJECT,BODY.

       Args:
         msgs_details: dictionary, containing all unread messages date - sender,reciever,uuid,full date,subject,body.

       Returns:
         Nothing.
       """
        for msg in msgs_details:
            try:
                date = self.fulldate_to_time(msg["Date"])
                uuid = self.extract_uuid(msg["UUID"])
                if uuid is None or date is None:
                    raise DateUidException
                file_name = date + " " + uuid + ".json"

                # Pops the date and uuid values that are not longer necessary for the json file.
                msg.pop("Date", None)
                msg.pop("UUID", None)

                # Determining the path for files.
                complete_file_name = os.path.join(self.path, file_name)
                with open(complete_file_name, "w") as f:
                    json.dump(msg, f)
            except (Exception, EnvironmentError) as e:
                    logger.exception(f"Error occured at {inspect.currentframe().f_code.co_name}.\n", e)


    def mark_as_read(self, service, messages, user_id):
        """Marks all unread messages as read.

       Args:
         service: connector object, the object for use the API
         messages: list, containing messages dictionarys(with ids)
         user_id: string, the user's id

       Returns:
         Nothing.
       """
        try:
            for msg in messages:
                service.users().messages().modify(
                    userId=user_id, id=msg["id"], body={"removeLabelIds": ["UNREAD"]}
                ).execute()

        except Exception:
            return print(
                "Error occured at {}".format(inspect.currentframe().f_code.co_name)
            )

    def get_unread_messages(self, service, user_id):
        """Gets all user's unread messages.

          Args:
            service: connector object, the object for use the API
            user_id: string, the user's id

          Returns:
            a dictionary with value of list of all mesagges ids
           """
        try:
            # List of all unread messages ids
            messages_ids = (
                service.users()
                .messages()
                .list(userId=user_id, labelIds=["INBOX"], q="is:unread")
                .execute()
            )

            # Case no new messages
            if messages_ids["resultSizeEstimate"] == 0:
                return print("No new messages")
            else:
                # Gets the actual messages dict using message id
                messages = messages_ids.get("messages", [])
                print(
                    "You have {} new messages".format(
                        messages_ids["resultSizeEstimate"]
                    )
                )
                return messages
        except Exception:
            return print(
                "Error occured at {}".format(inspect.currentframe().f_code.co_name)
            )

    def get_message(self, service, message, user_id):
        """Gets a specifiec message using message id.

          Args:
            service: connector object, the object for use the API
            message: dictinary, containts message id
            user_id: string, the user's id

          Returns:
            dictionary containing all message data
           """
        return (
            service.users().messages().get(userId=user_id, id=message["id"]).execute()
        )

    def parse_message(self,headers,msg):
        for header in headers:
            name = header["name"]
            if name == "To":
                reciever = header["value"]
            elif name == "From":
                sender = header["value"]
            elif name == "Subject":
                subject = header["value"]
            elif name == "Message-ID":
                uuid = header["value"]
            elif name == "Date":
                date = header["value"]
        new_msg = {
            "Sender": sender,
            "Reciever": reciever,
            "Subject": subject,
            "Body": msg["snippet"],
            "UUID": uuid,
            "Date": date
        }
        return new_msg

    def get_messages_details(self, service, messages, user_id):
        """Gets all messages requierd data - sender,reciever,uuid,date,subject,body.

          Args:
            service: connector object, the object for use the API
            messages: list, containing all unread messages dictionarys
            user_id: string, the user's id

          Returns:
            a dictionary with all requierd data
           """
        # This list will contain all the new messages with ID,DATE,SUBJECT,SENDER,RECIEVER,BODY values.
        all_new_msgs = []
        for message in messages:
            # For each message, gets the specified msg with msg_id
            msg = self.get_message(service, message, user_id)

            # From 'msg', gets list of all the HEADERS with the necessary data. when it finds required header name(SUBJECT,SENDER.....).
            # Header consist of "name" : (header's name), "value": (value)
            msg_headers = msg["payload"]["headers"]
            new_msg = self.parse_message(msg_headers,msg)
            all_new_msgs.append(new_msg)

        return all_new_msgs

    def get_service(self):
        """Creates the connection to GMAIL API.

          Args:
            None

          Returns:
            a connector object
           """
        self.creds = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists("token.pickle"):
            with open("token.pickle", "rb") as token:
                self.creds = pickle.load(token)
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", self.SCOPES
                )
                self.creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open("token.pickle", "wb") as token:
                pickle.dump(self.creds, token)

        service = build("gmail", "v1", credentials=self.creds)

        return service

    def start_reading_message_periodcaly(self, my_service):
        """Starts the fetch,mark,save messages process. Run periodcally, default-every 10 seconds.

          Args:
            my_service: connector object, the object for use the API

          Returns:
            Nothing.
           """
        # List of dicts containing messages ids
        messges_list = self.get_unread_messages(my_service, "me")
        if messges_list is not None:
            # dict with all the unread messages date: SENDER,RECIEVER,SUBJECT,ID,UUID,BODY
            new_msgs = self.get_messages_details(my_service, messges_list, "me")
            self.mark_as_read(my_service, messges_list, "me")
            self.save_messages(new_msgs)

        # Starts another interval after specified time with self.interval
        threading.Timer(
            self.interval, self.start_reading_message_periodcaly, [my_service]
        ).start()

