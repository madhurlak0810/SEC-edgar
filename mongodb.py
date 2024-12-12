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
import copy
import datetime
import Levenshtein as Levenshtein
from bs4 import NavigableString
from unidecode import unidecode
import string
import re
import traceback

DB_NAME = 'company_eval'

def make_edgar_request(url):
    """
    Make a request to EDGAR (Electronic Data Gathering, Analysis and Retrieval)
    :param url:
    :return: response
    """
    headers={
    "User-Agent": "radnom@ten.edu",
    "Accept-Encoding": "gzip, deflate"
    }
    response = requests.get(url, headers=headers)
    return response

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
        print("form")
        accession_no_symbols = filings["accessionNumber"][i].replace("-", "")
        primary_document = filings["primaryDocument"][i]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_trailing}/{accession_no_symbols}/{primary_document}"
        
        # if we already have the document, we don't download it again
        if check_document_exists("documents", url):
            continue
        
        print(f"{filing_date} ({form_type}): {url}")
        download_document(url, cik, form_type, filing_date,None)
        
        # insert a quick sleep to avoid reaching edgar rate limit
        time.sleep(5)
        
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

# This is a list of strings that we use to look for the table of contents in a 10-K filing
list_10k_items = [
    "business",
    "risk factors",
    "unresolved staff comments",
    "properties",
    "legal proceedings",
    "mine safety disclosures",
    "market for registrant’s common equity, related stockholder matters and issuer purchases of equity securities",
    "reserved",
    "management’s discussion and analysis of financial condition and results of operations",
    "quantitative and qualitative disclosures about market risk",
    "financial statements and supplementary data",
    "changes in and disagreements with accountants on accounting and financial disclosure",
    "controls and procedures",
    "other information",
    "disclosure regarding foreign jurisdictions that prevent inspection",
    "directors, executive officers, and corporate governance",
    "executive compensation",
    "security ownership of certain beneficial owners and management and related stockholder matters",
    "certain relationships and related transactions, and director independence",
    "principal accountant fees and services",
    "exhibits and financial statement schedules",
]

# This is a dictionary of default sections that a 10-K filing, annual report, could contain
default_10k_sections = {
     1: {'item': 'item 1', 'title': ['business']},
     2: {'item': 'item 1a', 'title': ['risk factor']},
     3: {'item': 'item 1b', 'title': ['unresolved staff']},
     4: {'item': 'item 2', 'title': ['propert']},
     5: {'item': 'item 3', 'title': ['legal proceeding']},
     6: {'item': 'item 4', 'title': ['mine safety disclosure', 'submission of matters to a vote of security holders']},
     7: {'item': 'item 5', 'title': ["market for registrant's common equity, related stockholder matters and issuer purchases of equity securities"]},
     8: {'item': 'item 6', 'title': ['reserved', 'selected financial data']},
     9: {'item': 'item 7', 'title': ["management's discussion and analysis of financial condition and results of operations"]},
     10: {'item': 'item 7a', 'title': ['quantitative and qualitative disclosures about market risk']},
     11: {'item': 'item 8', 'title': ['financial statements and supplementary data']},
     12: {'item': 'item 9', 'title': ['changes in and disagreements with accountants on accounting and financial disclosure']},
     13: {'item': 'item 9a', 'title': ['controls and procedures']},
     14: {'item': 'item 9b', 'title': ['other information']},
     15: {'item': 'item 9c', 'title': ['Disclosure Regarding Foreign Jurisdictions that Prevent Inspections']},
     16: {'item': 'item 10', 'title': ['directors, executive officers and corporate governance','directors and executive officers of the registrant']},
     17: {'item': 'item 11', 'title': ['executive compensation']},
     18: {'item': 'item 12', 'title': ['security ownership of certain beneficial owners and management and related stockholder matters']},
     19: {'item': 'item 13', 'title': ['certain relationships and related transactions']},
     20: {'item': 'item 14', 'title': ['principal accountant fees and services']},
     21: {'item': 'item 15', 'title': ['exhibits, financial statement schedules', 'exhibits and financial statement schedules']},
}

# This is a list of strings that we use to look for the table of contents in a 10-Q filing
list_10q_items = [
    "financial statement",
    "risk factor",
    "legal proceeding",
    "mine safety disclosure",
    "management’s discussion and analysis of financial condition and results of operations",
    "quantitative and qualitative disclosures about market risk",
    "controls and procedures",
    "other information",
    "unregistered sales of equity securities and use of proceeds",
    "defaults upon senior securities",
    "exhibits"
]

# This is a dictionary of default sections that a 10-Q filing, quarterly report, could contain
default_10q_sections = {
    1: {'item': 'item 1', 'title': ['financial statement']},
    2: {'item': 'item 2', 'title': ["management's discussion and analysis of financial condition and results of operations"]},
    3: {'item': 'item 3', 'title': ['quantitative and qualitative disclosures about market risk']},
    4: {'item': 'item 4', 'title': ['controls and procedures']},
    5: {'item': 'item 1', 'title': ['legal proceeding']},
    6: {'item': 'item 1a', 'title': ['risk factor']},
    7: {'item': 'item 2', 'title': ["unregistered sales of equity securities and use of proceeds"]},
    8: {'item': 'item 3', 'title': ["defaults upon senior securities"]},
    9: {'item': 'item 4', 'title': ["mine safety disclosure"]},
    10: {'item': 'item 5', 'title': ["other information"]},
    11: {'item': 'item 6', 'title': ["exhibits"]},
}

# This is a dictionary of default sections that a 8-K filing, current report, could contain
default_8k_sections = {
    1: {'item': 'item 1.01', 'title': ["entry into a material definitive agreement"]},
    2: {'item': 'item 1.02', 'title': ["termination of a material definitive agreement"]},
    3: {'item': 'item 1.03', 'title': ["bankruptcy or receivership"]},
    4: {'item': 'item 1.04', 'title': ["mine safety"]},
    5: {'item': 'item 2.01', 'title': ["completion of acquisition or disposition of asset"]},
    6: {'item': 'item 2.02', 'title': ['results of operations and financial condition']},
    7: {'item': 'item 2.03', 'title': ["creation of a direct financial obligation"]},
    8: {'item': 'item 2.04', 'title': ["triggering events that accelerate or increase a direct financial obligation"]},
    9: {'item': 'item 2.05', 'title': ["costs associated with exit or disposal activities"]},
    10: {'item': 'item 2.06', 'title': ["material impairments"]},
    11: {'item': 'item 3.01', 'title': ["notice of delisting or failure to satisfy a continued listing"]},
    12: {'item': 'item 3.02', 'title': ["unregistered sales of equity securities"]},
    13: {'item': 'item 3.03', 'title': ["material modification to rights of security holders"]},
    14: {'item': 'item 4.01', 'title': ["changes in registrant's certifying accountant"]},
    15: {'item': 'item 4.02', 'title': ["non-reliance on previously issued financial statements"]},
    16: {'item': 'item 5.01', 'title': ["changes in control of registrant"]},
    17: {'item': 'item 5.02', 'title': ['departure of directors or certain officers']},
    18: {'item': 'item 5.03', 'title': ['amendments to articles of incorporation or bylaws']},
    19: {'item': 'item 5.04', 'title': ["temporary suspension of trading under registrant"]},
    20: {'item': 'item 5.05', 'title': ["amendment to registrant's code of ethics"]},
    21: {'item': 'item 5.06', 'title': ["change in shell company status"]},
    22: {'item': 'item 5.07', 'title': ['submission of matters to a vote of security holders']},
    23: {'item': 'item 5.08', 'title': ["shareholder director nominations"]},
    24: {'item': 'item 6.01', 'title': ["abs informational and computational material"]},
    25: {'item': 'item 6.02', 'title': ['change of servicer or trustee']},
    26: {'item': 'item 6.03', 'title': ['change in credit enhancement or other external support']},
    27: {'item': 'item 6.04', 'title': ["failure to make a required distribution"]},
    28: {'item': 'item 6.05', 'title': ["securities act updating disclosure"]},
    29: {'item': 'item 7.01', 'title': ["regulation fd disclosure"]},
    30: {'item': 'item 8.01', 'title': ['other events']},
    31: {'item': 'item 9.01', 'title': ["financial statements and exhibits"]},
}

def identify_table_of_contents(soup, list_items):
    """
    Given a soup object and a list of item, this method looks for a table of contents.
    :param soup: soup object of the document
    :param list_items: an array of strings related to sections titles.
    :return: the table of contents PageElement object or None if not found.
    """
    if list_items is None:
        return None
    max_table = 0
    chosen_table = None
    tables = soup.body.findAll("table")
    
    # for each table in the document
    for t in tables:
        
        # count how many elements of list_items are present in the table
        count = 0
        for s in list_items:
            r = t.find(string=re.compile(f'{s}', re.IGNORECASE))
            if r is not None:
                count += 1

        # choose the table that has the maximum number of elements
        if count > max_table:
            chosen_table = t
            max_table = count
                   
    # we return the chosen table only if it has at least 3 elements
    if max_table > 3:
        return chosen_table
    
    return None

def get_sections_text_with_hrefs(soup, sections):
    """
    This method tries to retrieve text from soup object related to a document and its sections
    :param soup: a soup object
    :param sections: a dictionary containing data about sections
    :return: 
    """
    next_section = 1
    current_section = None
    text = ""
    last_was_new_line = False
    
    # for each element in body
    for el in soup.body.descendants:
        
        # if we find the start element of a section
        if next_section in sections and el == sections[next_section]['start_el']:
            
            # set current_section = text and reset text to empty string
            if current_section is not None:
                sections[current_section]["text"] = text
                text = ""
                last_was_new_line = False

            # change section
            current_section = next_section
            next_section += 1

        # if we are currently in a section
        if current_section is not None and isinstance(el, NavigableString):
            
            if last_was_new_line and el.text == "\n":
                continue
            elif el.text == "\n":
                last_was_new_line = True
            else:
                last_was_new_line = False
            found_text = unidecode(el.get_text(separator=" "))
            
            # append to text
            if len(text) > 0 and text[-1] != " " and len(found_text) > 0 and found_text[0] != " ":
                text += "\n"
            text += found_text.replace('\n', ' ')

    # we reached the end of the document, set current_section = text
    if current_section is not None:
        sections[current_section]["text"] = text

    return sections

def clean_section_title(title):
    """
    Clean the title string removing special words and punctuation that makes harder to recognize it.
    :param title: a string
    :return: a cleaned string, lowercase
    """
    
    # lower case
    title = title.lower()
    
    # remove special html characters
    title = unidecode(title)
    
    # remove item
    title = title.replace("item ", "")
    
    # remove '1.' etc
    for idx in range(20, 0, -1):
        for let in ['', 'a', 'b', 'c']:
            title = title.replace(f"{idx}{let}.", "")
    for idx in range(10, 0, -1):
        title = title.replace(f"f-{idx}", "")
    
    # remove parentesis and strip
    title = re.sub(r'\([^)]*\)', '', title).strip(string.punctuation + string.whitespace)
    
    return title

def get_sections_using_hrefs(soup, table_of_contents):
    """
    Scan the table_of_contents and identify all hrefs, if present.
    The method create a dictionary of sections by finding tag elements referenced inside soup with the specific hrefs.
    :param soup: soup object of the document.
    :param table_of_contents:
    :return: a dictionary with the following structure:
        {1:
            {
                'start_el': tag element where the section starts,
                'idx': an integer index of start element inside soup, used for ordering
                'title': a string representing the section title,
                'title_candidates': a list of title candidates. If there is a single candidate that becomes the title
                'end_el': tag element where the section ends,
                'text': the text of the section
            },
        ...
        }
        Section are ordered based on chid['idx'] value
    :param soup:
    :return: section dictionary
    """
    
    # get all html elements
    all_elements = soup.find_all()
    hrefs = {}
    sections = {}
    
    # for each row in table of contents
    for tr in table_of_contents.findAll("tr"):
        
        # get all <a> tags and their links
        try:
            aa = tr.find_all("a")
            tr_hrefs = [a['href'][1:] for a in aa]
            
        except Exception as e:
            continue

        # for each element in the table row
        for el in tr.children:
            
            text = el.text
            text = clean_section_title(text)
            
            # check if there is a title
            if is_title_valid(text):
                
                
                for tr_href in tr_hrefs:
                    if tr_href not in hrefs:
                        
                        # find a document related to that title
                        h_tag = soup.find(id=tr_href)
                        if h_tag is None:
                            h_tag = soup.find(attrs={"name": tr_href})
                            
                        # if we find one, we store the information in our hrefs dictionary
                        if h_tag:
                            hrefs[tr_href] = {
                                'start_el': h_tag,
                                'idx': all_elements.index(h_tag),
                                'title': None,
                                'title_candidates': set([text])}
                    else:
                        hrefs[tr_href]['title_candidates'].add(text)
            else:
                continue

    # for each element in our hrefs dictionary (title information)
    for h in hrefs:
        hrefs[h]['title_candidates'] = list(hrefs[h]['title_candidates'])
        if len(hrefs[h]['title_candidates']) == 1:
            hrefs[h]['title'] = hrefs[h]['title_candidates'][0]
        else:
            hrefs[h]['title'] = "+++".join(hrefs[h]['title_candidates'])

    # let's sort the titles based on where we found the corresponding element in the document.
    # It can happen (seldom) that an element that comes before in the table of contents, 
    # actually comes after in the document
    temp_s = sorted(hrefs.items(), key=lambda x: x[1]["idx"])
    for i, s in enumerate(temp_s):
        sections[i + 1] = s[1]
        if i > 0:
            sections[i]["end_el"] = sections[i + 1]["start_el"]

    # retrieve sections text
    sections = get_sections_text_with_hrefs(soup, sections)
    return sections

def string_similarity_percentage(string1, string2):
    """
    Compute the leveshtein distance between the two strings and return the percentage similarity.
    :param string1: 
    :param string2: 
    :return: a float representing the percentage of similarity
    """
    distance = Levenshtein.distance(string1.replace(" ", ""), string2.replace(" ", ""))
    max_length = max(len(string1), len(string2))
    similarity_percentage = (1 - (distance / max_length)) * 100
    return similarity_percentage

def is_title_valid(text):
    """
    Check if title is valid, meaning;
    it does not starts with key words like: item, part, signature, page or is digit and has less than 2 chars
    :param text: a string representing the title
    :return: True if all conditions are satisfied else False
    """
    valid = not (
            text.startswith("item") or
            text.startswith("part") or
            text.startswith("signature") or
            text.startswith("page") or
            text.isdigit() or
            len(text) <= 2)
    return valid

def select_best_match(string_to_match, matches, start_index):
    """
    Identifies the best match, in terms of similarity distance between a string_to_match and a list of matches.
    start_index is used to avoid cases where the string_to_match is matched with the first occurence in matches.
    :param string_to_match: a string
    :param matches: a list of regular expresion matches
    :param start_index: a integer representing the index to start from
    :return: a regualr expression match with highest simialrity
    """
    match = None

    if start_index == 0:
        del matches[0]

    # if there is only one possibility
    if len(matches) == 1:
        match = matches[0]
        if matches[0].start() > start_index:
            match = matches[0]
            
    # else search for the most similar option
    elif len(matches) > 1:
        max_similarity = -1
        for i, m in enumerate(matches):
            if m.start() > start_index:
                sim = string_similarity_percentage(string_to_match, m.group().lower().replace("\n", " "))
                if sim > max_similarity:
                    max_similarity = sim
                    match = m
    return match

def get_sections_using_strings(soup, table_of_contents, default_sections):
    """
        Scan the table_of_contents and identify possible section text using strings that match default_sections.
        Retrieve sections strings in soup.body.text.
        :param soup: the soup object
        :param table_of_contents: a PageElement from soup that represent the table of contents
        :param default_sections: a dictionary that contains prefilled data about default sections that could be found in the document
        :return: a dictionary with the following structure, representing the sections:
            {1:
                {
                    'start_index': the start index of the section inside soup.body.text
                    'end_index': the start index of the section inside soup.body.text,
                    'title': a string representing the section title,
                    'end_el': tag element where the section ends
                },
            ...
            }
            Section are ordered based on chid['idx'] value
        """

    # Clean soup.body.text removing consecutive \n and spaces
    body_text = unidecode(soup.body.get_text(separator=" "))
    body_text = re.sub('\n', ' ', body_text)
    body_text = re.sub(' +', ' ', body_text)

    # If there is a table_of_contents look for items strings a check for their validity
    sections = {}
    if table_of_contents:
        num_section = 1
        for tr in table_of_contents.findAll("tr"):
            section = {}
            for el in tr.children:
                text = el.text
                
                # remove special html characters
                item = unidecode(text.lower()).replace("\n", " ").strip(string.punctuation + string.whitespace)

                if 'item' in item:
                    section["item"] = item

                text = clean_section_title(text)
                if 'item' in section and is_title_valid(text):
                    section['title'] = text
                    sections[num_section] = section
                    num_section += 1
    
    # Different behaviour if there is a table_of_contents and sections is already populated.
    if len(sections) == 0:
        # no usable table_of_contents sections, we use a prefilled default_sections dictionary
        sections = copy.deepcopy(default_sections)
        start_index = 1
    else:
        # skip first occurrence in text since it also present in table_of_contents
        start_index = 0
    
    # Loop through all sections to identify a possible item and title for a section.
    # If multiple values are found we select best match based on string similarity.
    for si in sections:
        s = sections[si]
        if 'item' in s:
            match = None
            if isinstance(s['title'], list):
                for t in s['title']:
                    matches = list(re.finditer(fr"{s['item']}. *{t}", body_text, re.IGNORECASE + re.DOTALL))
                    if matches:
                        match = select_best_match(f"{s['item']} {t}", matches, start_index)
                        break
            else:
                matches = list(re.finditer(fr"{s['item']}. *{s['title']}", body_text, re.IGNORECASE + re.DOTALL))
                if matches:
                    match = select_best_match(f"{s['item']} {s['title']}", matches, start_index)

            if match is None:
                matches = list(re.finditer(fr"{s['item']}", body_text, re.IGNORECASE + re.DOTALL))
                if matches:
                    match = select_best_match(f"{s['item']}", matches, start_index)

            if match:
                s['title'] = match.group()
                s["start_index"] = match.start()
                start_index = match.start()
            else:
                s['remove'] = True

    sections_temp = {}
    for si in sections:
        if "remove" not in sections[si]:
            sections_temp[si] = sections[si]

    # Eventually we populate each section in the dictionary with its text taken from body_text
    temp_s = sorted(sections_temp.items(), key=lambda x: x[1]["start_index"])
    sections = {}
    last_section = 0
    for i, s in enumerate(temp_s):
        sections[i + 1] = s[1]
        if i > 0:
            sections[i]["end_index"] = sections[i + 1]["start_index"]
            sections[i]["text"] = body_text[sections[i]["start_index"]:sections[i]["end_index"]]
        last_section = i + 1
    if last_section > 0:
        sections[last_section]["end_index"] = -1
        sections[last_section]["text"] = body_text[sections[last_section]["start_index"]:sections[last_section]["end_index"]]

    return sections

def parse_document(doc):
    """
    Take a document, SEC filing, parse the content and retrieve the sections.
    Save the result in MongoDB under parsed_documents collection.
    :param doc: document from "documents" collection of mongoDB
    :return:
    """

    url = doc["_id"]
    form_type = doc["form_type"]
    filing_date = doc["filing_date"]
    sections = {}
    cik = doc["cik"]
    html = doc["html"]

    # Supported form type are 10-K, 10-K/A, 10-Q, 10-Q/A, 8-K
    if form_type in ["10-K", "10-K/A"]:
        include_forms = ["10-K", "10-K/A"]
        list_items = list_10k_items
        default_sections = default_10k_sections
    elif form_type == "10-Q":
        include_forms = ["10-Q", "10-Q/A"]
        list_items = list_10q_items
        default_sections = default_10q_sections
    elif form_type == "8-K":
        include_forms = ["8-K"]
        list_items = None
        default_sections = default_8k_sections
    else:
        print(f"return because form_type {form_type} is not valid")
        return

    if form_type not in include_forms:
        print(f"return because form_type != {form_type}")
        return

    company_info = company_from_cik(cik)

    # no cik in cik_map
    if company_info is None:
        print("return because company info None")
        return

    print(f"form type: \t\t{form_type}")
    print(company_info)

    soup = BeautifulSoup(html, features="html.parser")

    if soup.body is None:
        print("return because soup.body None")
        return

    table_of_contents = identify_table_of_contents(soup, list_items)

    if table_of_contents:
        sections = get_sections_using_hrefs(soup, table_of_contents)

    if len(sections) == 0:
        sections = get_sections_using_strings(soup, table_of_contents, default_sections)

    result = {"_id": url, "cik": cik, "form_type":form_type, "filing_date": filing_date, "sections":{}}

    for s in sections:
        section = sections[s]
        if 'text' in section:
            text = section['text']
            text = re.sub('\n', ' ', text)
            text = re.sub(' +', ' ', text)

            result["sections"][section["title"]] = {"text":text, "link":section["link"] if "link" in section else None}

    try:
        upsert_document("parsed_documents", result)
    except:
        traceback.print_exc()
        print(result.keys())
        print(result["sections"].keys())