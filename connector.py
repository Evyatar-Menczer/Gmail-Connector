import pickle
import os.path
import json
import inspect
import threading
import logzero
from logzero import logger
from googleapiclient import errors
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dateutil import parser


class GmailConnector:

    TOKEN_PICKLE = "token.pickle"
    SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
    USER_ID = "me"
    logger = logzero.setup_logger(maxBytes=int(1e6), disableStderrLogger=True)

    def __init__(self, config_file: str = None):
        """Initializes default values

        Args:
            self.interval: int, determines running period
            self.path: string, saving json files path
            self.required_headers: list, requierd data to fetch from the message.

          """
        self.creds = None
        self.path = "."
        self.interval = 10
        self.is_running = False
        self.connector = None
        self.required_headers = ["To", "From", "Subject", "UUID", "Date", "Message-ID"]
        if config_file:
            self.init_with_config_file(config_file)

    def init_with_config_file(self, file: str) -> None:
        """Initializes the connector values - creds,path,interval(from the file)
         in case config file is given.

      Args:
        file: file's name.

      Returns:
        None.
      """
        with open(file) as config_file:
            data = json.load(config_file)
        for key, val in data.items():
            if key.lower() == "credentials":
                self.creds = val
            elif key == "path":
                self.path = val
            elif key == "interval":
                self.interval = val

    def save_messages(self, messages: list) -> None:
        """Save all messages as .json file in format SENDER,RECIEVER,SUBJECT,BODY.

       Args:
         messages: containing all messages date - sender,reciever,uuid,full date,subject,body.

       Returns:
         None.
       """
        for msg in messages:
            try:
                date = self.__fulldate_to_time(msg["Date"])
                uuid = self.__extract_uuid(msg["UUID"])
                if uuid is None or date is None:
                    raise DateUuidException
                file_name = "{} {}.json".format(date, uuid)

                # Pops the date and uuid values that are not longer necessary for the json file.
                msg.pop("Date", None)
                msg.pop("UUID", None)

                # Determining the path for files.
                complete_file_name = os.path.join(self.path, file_name)
                with open(complete_file_name, "w") as f:
                    json.dump(msg, f)
            except (errors.HttpError, AttributeError) as e:
                logger.exception(
                    "Error occured at {}\n".format(
                        inspect.currentframe().f_code.co_name
                    ),
                    e,
                )

    def mark_as_read(self, messages: list) -> None:
        """Marks all unread messages as read.

       Args:
         messages: list, containing messages dictionarys(with ids)

       Returns:
         Nothing.
       """
        try:
            for msg in messages:
                self.connector.users().messages().modify(
                    userId=self.USER_ID,
                    id=msg["id"],
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute()

        except errors.HttpError as e:
            logger.exception(
                "Error occured at {}\n".format(inspect.currentframe().f_code.co_name), e
            )

    def get_unread_messages(self) -> dict:
        """Gets all user's unread messages.

          Args:
            None.
          Returns:
            A dictionary with value of list of all mesagges ids.
           """
        try:
            # List of all unread messages ids
            messages_ids = (
                self.connector.users()
                .messages()
                .list(userId=self.USER_ID, labelIds=["INBOX"], q="is:unread")
                .execute()
            )

            # Case no new messages
            if messages_ids["resultSizeEstimate"] == 0:
                return logger.info("No new messages")
            else:
                # Gets the actual messages dict using message id
                messages = messages_ids.get("messages", [])
                logger.info(
                    "You have {} new messages.".format(
                        messages_ids["resultSizeEstimate"]
                    )
                )
                return messages
        except (Exception, errors.HttpError) as e:
            logger.exception(
                "Error occured at {}\n".format(inspect.currentframe().f_code.co_name), e
            )

    def get_message(self, message: dict) -> dict:
        """Gets a specifiec message using message id.

          Args:
            message: dictinary, containts message id

          Returns:
            dictionary containing all message data
           """
        return (
            self.connector.users()
            .messages()
            .get(userId=self.USER_ID, id=message["id"])
            .execute()
        )

    def parse_message(self, headers: dict) -> dict:
        """Gets all messages requierd data - sender,reciever,uuid,date,subject,body.

          Args:
            headers: dictionary contains all message headers.

          Returns:
            A dictionary with all requierd data of message, specified in self.headers
           """
        new_msg = {}
        for header in headers:
            name = header["name"]
            if name in self.required_headers:
                new_msg[name] = header["value"]
        return new_msg

    def get_messages_details(self, messages: list) -> dict:
        """Gets all messages requierd data - sender,reciever,uuid,date,subject,body.

          Args:
            messages: list, containing all unread messages dictionarys.

          Returns:
            A dictionary with all requierd data.
           """
        # This list will contain all the new messages with ID,DATE,SUBJECT,SENDER,RECIEVER,BODY values.
        all_new_msgs = []
        try:
            for message in messages:
                # For each message, gets the specified msg with msg_id
                msg = self.get_message(message)

                # From 'msg', gets list of all the HEADERS with the necessary data. when it finds required header name(SUBJECT,SENDER.....).
                msg_headers = msg["payload"]["headers"]
                new_msg = self.parse_message(msg_headers)

                # Message's body not in Headers.
                new_msg["Body"] = msg["snippet"]
                all_new_msgs.append(new_msg)
        except (errors.HttpError, AttributeError) as e:
            logger.exception(
                "Error occured at {}\n".format(inspect.currentframe().f_code.co_name), e
            )
        return all_new_msgs

    def start_reading_messages(self) -> None:
        """Initializes the connector and starts the reading messages process.

          Args:
            None.

          Returns:
            None.
           """
        if self.connector is None:
            try:
                self.connector = self.__init_connector()
            except (errors.HttpError, AttributeError) as e:
                logger.exception(
                    "Error occured at {}\n".format(
                        inspect.currentframe().f_code.co_name
                    ),
                    e,
                )
        self.is_running = True
        self.__read_messages_periodcally()

    def stop_reading_messages(self) -> None:
        """Stops the reading process.

          Args:
            None.

          Returns:
            None.
           """
        self.is_running = False

    def __read_messages_periodcally(self):
        """Starts the fetch,mark,save messages process. Run periodcally, default-every 10 seconds.

              Args:
                None.
              Returns:
                None.
               """
        # For stop.
        if not self.is_running:
            return
        try:
            logger.info("Started iteration")
            # List of dicts containing messages ids
            messges_list = self.get_unread_messages()
            if messges_list is not None:
                # dict with all the unread messages date: SENDER,RECIEVER,SUBJECT,ID,UUID,BODY
                new_msgs = self.get_messages_details(messges_list)
                self.mark_as_read(messges_list)
                self.save_messages(new_msgs)

            # Starts another interval after specified time with self.interval
            threading.Timer(self.interval, self.__read_messages_periodcally).start()
            logger.info("Finished iteration")
        except (errors.HttpError, AttributeError) as e:
            logger.exception(
                "Error occured at {}\n".format(inspect.currentframe().f_code.co_name), e
            )

    def __init_connector(self):
        """Creates the connection to GMAIL API.

          Args:
            None

          Returns:
            A connector object
           """
        self.creds = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists(self.TOKEN_PICKLE):
            with open(self.TOKEN_PICKLE, "rb") as token:
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
            with open(self.TOKEN_PICKLE, "wb") as token:
                pickle.dump(self.creds, token)

        service = build("gmail", "v1", credentials=self.creds)

        return service

    def __fulldate_to_time(self, date: str) -> str:
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
        except (Exception, SyntaxError) as e:
            logger.exception(
                "Error in {} \n".format(inspect.currentframe().f_code.co_name), e
            )
            return None
        return time_str

    def __extract_uuid(self, uuid: str) -> str:
        """Converts full uuid to a valid file name(remove invalid characters - \/:*?"<>| ).

    For exmaple,'<CAFyznE0J9meRG9mFdqwg9OnVYwATbcLeNAEJwvZb_=aQcPJq2w@mail.gmail.com>' ->

                'CAFyznE0J9meRG9mFdqwg9OnVYwATbcLeNAEJwvZb_=aQcPJq2w'

      Args:
        uuid: string, the full uuid as taken from the message.

      Returns:
        Valid uuid for file's name.
      """
        try:
            fixed_uuid = uuid.split("@")[0]
            chars_to_replace = '\/:*?"<>|'
            for char in chars_to_replace:
                if char in fixed_uuid:
                    fixed_uuid = fixed_uuid.replace(char, "")
        except (EnvironmentError, AttributeError) as e:
            logger.excpetion(
                "Error at {}\n".format(inspect.currentframe().f_code.co_name), e
            )
            return None
        return fixed_uuid


class DateUuidException(Exception):
    """Class for any exception occurs while dealing with
        __fulldate_to_time and __extract_uuid.
      """

    pass
