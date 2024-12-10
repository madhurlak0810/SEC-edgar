from configparser import ConfigParser
from pymongo import MongoClient
import os
import datetime
from dateutil.relativedelta import relativedelta
import time
import sys
from pymongo.errors import DocumentTooLarge
import requests
import pandas as pd
from bs4 import BeautifulSoup
import json
import socket

DB_NAME = 'company_eval'

def make_edgar_request(url):
    """
    Make a request to EDGAR (Electronic Data Gathering, Analysis and Retrieval)
    :param url:
    :return: response
    """
    headers = {
        "User-Agent": "your.email@email.com"
    }
    return requests.get(url, headers=headers)

def get_mongodb_client():
    """
    Get mongodb client
    :return: mongodb client
    """
    socket.getaddrinfo('localhost', 8080)
    # Get credentials
    parser = ConfigParser()
    _ = parser.read(os.path.join("credentials.cfg"))
    username = parser.get("mongo_db", "username")
    password = parser.get("mongo_db", "password")

    # Set connection string
    #LOCAL_CONNECTION = "mongodb://localhost:27017"
    ATLAS_CONNECTION = f"mongodb+srv://{username}:{password}@cluster0.rrvyc.mongodb.net/" \
                       f"retryWrites=true&w=majority"
    ATLAS_OLD_CONNECTION = f"mongodb://{username}:{password}@cluster0.rrvyc.mongodb.net:27017/?" \
                          f"retryWrites=true&w=majority&tls=true"

    connection_string = ATLAS_CONNECTION

    # Create a connection using MongoClient
    client = MongoClient(host=connection_string,connect=False)

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

def download_document(url, cik, form_type, filing_date,updated_at=None):
    response = make_edgar_request(url)
    r = response.text
    doc = {"html": r, "cik": cik, "form_type": form_type, "filing_date": filing_date, "updated_at": updated_at, "_id": url}
    try:
        insert_document("documents", doc)
    except DocumentTooLarge:
        # DocumenTooLarge is raised by mongodb when uploading files larger than 16MB
        # To avoid this it is better to save this kind of files in a separate storate like S3 and retriving them when needed.
        # Another options could be using mongofiles: https://www.mongodb.com/docs/database-tools/mongofiles/#mongodb-binary-bin.mongofiles
        # for management of large files saved in mongo db.
        print("Document too Large (over 16MB)", url)
    pass

def download_all_cik_submissions(cik):
    """
    Get list of submissions for a single company.
    Upsert this list on MongoDB (each download contains all the submissions).
    :param cik: cik of the company
    :return:
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    response = make_edgar_request(url)
    r = response.json()
    r["_id"] = cik
    upsert_document("submissions", r)

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
        
def download_cik_ticker_map():
    """
    Get a mapping of cik (Central Index Key, id of company on edgar) and ticker on the exchange.
    It upsert the mapping in MongoDB collection cik_ticker.
    """
    CIK_TICKER_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
    response = make_edgar_request(CIK_TICKER_URL)
    html_content = response.content
    # Parse the HTML content using BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    r= json.loads(soup.text)
    r["_id"] = "cik_ticker"
    upsert_document("cik_ticker", r)
    
def get_df_cik_ticker_map():
    """
    Create a DataFrame from cik ticker document on MongoDB.
    :return: DataFrame
    """
    try:
        cik_ticker = get_collection_documents("cik_ticker").next()
    except StopIteration:
        print("cik ticker document not found")
        return
    df = pd.DataFrame(cik_ticker["data"], columns=cik_ticker["fields"])
    
    # add leading 0s to cik (always 10 digits)
    df["cik"] = df.apply(lambda x: add_trailing_to_cik(x["cik"]), axis=1)
    
    return df

def company_from_cik(cik):
    """
    Get company info from cik
    :param cik: company id on EDGAR
    :return: DataFrame row with company information (name, ticker, exchange)
    """
    df = get_df_cik_ticker_map()
    try:
        return df[df["cik"] == cik].iloc[0]
    except IndexError:
        return None

def cik_from_ticker(ticker):
    """
    Get company cik from ticker
    :param ticker: company ticker
    :return: cik (company id on EDGAR)
    """
    df = get_df_cik_ticker_map()
    try:
        cik = df[df["ticker"] == ticker]["cik"].iloc[0]
    except:
        cik = -1
    return cik

def add_trailing_to_cik(cik_no_trailing):
    return "{:010d}".format(cik_no_trailing)