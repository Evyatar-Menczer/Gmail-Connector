from connector import GmailConnector

if __name__ == "__main__":
    connector = GmailConnector()
    connector.start_reading_messages()
