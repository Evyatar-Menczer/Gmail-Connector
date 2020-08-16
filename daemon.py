from connector import GmailConnector

if __name__ == "__main__":
    connector = GmailConnector()
    service = connector.get_service()
    connector.start_reading_message_periodcaly(service)
