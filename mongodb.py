from configparser import ConfigParser
from pymongo import MongoClient
import os
import datetime
from dateutil.relativedelta import relativedelta
import time
import sys

DB_NAME = 'company_eval'

def make_edgar_request(url):
    """
    Make a request to EDGAR (Electronic Data Gathering, Analysis and Retrieval)
    :param url:
    :return: response
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
        "Accept-Encoding": "gzip, deflate, br",
    }
    return requests.get(url, headers=headers)

def get_mongodb_client():
    """
    Get mongodb client
    :return: mongodb client
    """
    # Get credentials
    parser = ConfigParser()
    _ = parser.read(os.path.join("credentials.cfg"))
    username = parser.get("mongo_db", "username")
    password = parser.get("mongo_db", "password")

    # Set connection string
    LOCAL_CONNECTION = "mongodb://localhost:27017"
    ATLAS_CONNECTION = f"mongodb+srv://{username}:{password}@cluster0.3dxfmjo.mongodb.net/?" \
                       f"retryWrites=true&w=majority"
    ATLAS_OLD_CONNECTION = f"mongodb://{username}:{password}@cluster0.3dxfmjo.mongodb.net:27017/?" \
                          f"retryWrites=true&w=majority&tls=true"

    connection_string = LOCAL_CONNECTION

    # Create a connection using MongoClient
    client = MongoClient(connection_string)

    return client

def get_collection(collection_name):
    db = get_mongodb_client()[DB_NAME]
    return db[collection_name]

def get_file_size(file_name):
    file_stats = os.stat(file_name)
    print(f'File Size in Bytes is {file_stats.st_size}')
    return file_stats.st_size

def get_dict_size(data):
    print("The size of the dictionary is {} bytes".format(sys.getsizeof(data)))
    return sys.getsizeof(data)

def upsert_document(collection_name, data):
    collection = get_collection(collection_name)
    collection.replace_one({"_id": data["_id"]}, data, upsert=True)

def insert_document(collection_name, data):
    collection = get_collection(collection_name)
    collection.insert_one(data)

def get_document(collection_name, document_id):
    collection = get_collection(collection_name)
    return collection.find({"_id": document_id}).next()

def check_document_exists(collection_name, document_id):
    collection = get_collection(collection_name)
    return collection.count_documents({"_id": document_id}, limit=1) > 0

def get_collection_documents(collection_name):
    collection = get_collection(collection_name)
    return collection.find({})

def download_document(url, cik, form_type, filing_date):
    response = make_edgar_request(url)
    r = response.text
    doc = {"html": r, "cik": cik, "form_type": form_type, "filing_date": filing_date, "updated_at": updated_at, "_id": url}
    try:
        mongodb.insert_document("documents", doc)
    except DocumentTooLarge:
        # DocumenTooLarge is raised by mongodb when uploading files larger than 16MB
        # To avoid this it is better to save this kind of files in a separate storate like S3 and retriving them when needed.
        # Another options could be using mongofiles: https://www.mongodb.com/docs/database-tools/mongofiles/#mongodb-binary-bin.mongofiles
        # for management of large files saved in mongo db.
        print("Document too Large (over 16MB)", url)
    pass

def download_submissions_documents(cik, forms_to_download=("10-Q", "10-K", "8-K"), years=5):
    """
    Download all documents for submissions forms 'forms_to_download' for the past 'years'.
    Insert them on mongodb.
    :param cik: company cik
    :param forms_to_download: a tuple containing the form types to download
    :param years: the max number of years to download
    :return:
    """
    try:
        submissions = get_document("submissions", cik)
    except StopIteration:
        print(f"submissions file not found in mongodb for {cik}")
        return
    
    cik_no_trailing = submissions["cik"]
    filings = submissions["filings"]["recent"]
    
    for i in range(len(filings["filingDate"])):
        filing_date = filings['filingDate'][i]
        difference_in_years = relativedelta(datetime.date.today(),
                                            datetime.datetime.strptime(filing_date, "%Y-%m-%d")).years
        
        # as the document are ordered chronologically when we reach the max history we can return
        if difference_in_years > years:
            return
        
        form_type = filings['form'][i]
        if form_type not in forms_to_download:
            continue
            
        accession_no_symbols = filings["accessionNumber"][i].replace("-", "")
        primary_document = filings["primaryDocument"][i]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_trailing}/{accession_no_symbols}/{primary_document}"
        
        # if we already have the document, we don't download it again
        if check_document_exists("documents", url):
            continue
        
        print(f"{filing_date} ({form_type}): {url}")
        download_document(url, cik, form_type, filing_date)
        
        # insert a quick sleep to avoid reaching edgar rate limit
        time.sleep(0.2)