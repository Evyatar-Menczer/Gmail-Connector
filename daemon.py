from connector import GmailConnector

if __name__ == "__main__":
    print(1e6)
    connector = GmailConnector()
    connector.start_reading_messages()
