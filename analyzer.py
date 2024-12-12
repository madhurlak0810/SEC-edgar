from typing import Any, List
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.document_loaders.unstructured import UnstructuredBaseLoader
from langchain.callbacks import get_openai_callback
from langchain.chains.summarize import load_summarize_chain
from langchain.chat_models import ChatOpenAI
from configparser import ConfigParser
import os
import mongodb as mongodb
import time
import re
from mongodb import company_from_cik

parser = ConfigParser()
_ = parser.read(os.path.join("credentials.cfg"))

class UnstructuredStringLoader(UnstructuredBaseLoader):
    """
    Uses unstructured to load a string
    Source of the string, for metadata purposes, can be passed in by the caller
    """

    def __init__(
        self, content: str, source: str = None, mode: str = "single",
        **unstructured_kwargs: Any
    ):
        self.content = content
        self.source = source
        super().__init__(mode=mode, **unstructured_kwargs)

    def _get_elements(self) -> List:
        from unstructured.partition.text import partition_text

        return partition_text(text=self.content, **self.unstructured_kwargs)

    def _get_metadata(self) -> dict:
        return {"source": self.source} if self.source else {}


def split_doc_in_chunks(doc, chunk_size=20000):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=100)
    chunks = text_splitter.split_documents(doc)
    return chunks

def compute_cost(tokens, model="gpt-3.5-turbo"):
    """
    Compute API cost from number of tokens
    :param tokens: the number of token
    :param model: the model name
    :return: cost in USD
    """
    if model == "gpt-3.5-turbo":
        return round(tokens / 1000 * 0.002, 4)
    if model == "gpt-3.5-turbo-16k":
        return round(tokens / 1000 * 0.004, 4)
    
def create_summary(section_text, model, chain_type="map_reduce", verbose=False):
    """
    Call OpenAI model with langchain library using ChatOpenAI.
    then call langchain.load_summarize_chain with the selected model and the chain_type
    :param section_text: text to be summarized
    :param model: language model
    :param chain_type: chain type for langchain.load_summarize_chain
    :param verbose: print langchain process
    :return: the model response, and the number of total tokens it took.
    """
    # load langchain language model
    llm = ChatOpenAI(model_name=model, openai_api_key=parser.get("open_ai", "api_key"))

    # prepare section_text string with a custom string loader to be ready for load_summarize_chain
    string_loader = UnstructuredStringLoader(section_text)

    # split the string in multiple chunks
    docs = split_doc_in_chunks(string_loader.load())

    # call model with the chain_type specified
    chain = load_summarize_chain(llm, chain_type=chain_type, verbose=verbose)

    # retrieve model response
    with get_openai_callback() as cb:
        res = chain.run(docs)

    return res, cb.total_tokens

def summarize_section(section_text, model="gpt-3.5-turbo", chain_type="map_reduce", verbose=False):
    """
    Create a summary for a document section.
    Output is a json {"data":["info1", "info2", ..., "infoN"]}
    :param section_text: text input to be summarized
    :param model:the OpenAI model to use, default is gpt-3.5-turbo
    :param chain_type: the type of chain to use for summarization, default is "map_reduce",
     possible other values are "stuff" and "refine"
    :param verbose: passed to langchain to print details about the chain process
    :return: bullet points of the summary as an array of strings and the cost of the request
    """
    # call model to create the summary
    summary, tokens = create_summary(section_text, model, chain_type, verbose)

    # split summary in bullet points using "." as separator
    bullets = [x.strip() for x in re.split(r'(?<!inc)(?<!Inc)\. ', summary)]

    # compute cost based on tokens of the response and the used model
    cost = compute_cost(tokens, model=model)

    return bullets, cost

def restructure_parsed_10k(doc):
    """
    Look for and select only the sections specified in result dictionary.
    :param doc: mongo document from "documents" collection
    :return: a dictionary containing the parsed document sections titles and their text.
    """
    result = {
        "business": {"text":"", "links":[]},
        "risk": {"text":"", "links":[]},
        "unresolved": {"text":"", "links":[]},
        "property": {"text":"", "links":[]},
        "legal": {"text":"", "links":[]},
        "foreign": {"text":"", "links":[]},
        "other": {"text":"", "links":[]},
        
        # we are not going to summarize MD&A and financial notes sections of the document, while both extremely important,
        # because we didn't manage to obtain useful results from OpenAI models, without further pre-processing.
        
        # "MD&A": {"text":"", "links":[]},
        # "notes": {"text":"", "links":[]},
        
    }

    for s in doc["sections"]:

        found = None
        if ("business" in s.lower() or "overview" in s.lower() or "company" in s.lower() or "general" in s.lower() or "outlook" in s.lower())\
                and not "combination" in s.lower():
            found = "business"
        elif "propert" in s.lower() and not "plant" in s.lower() and not "business" in s.lower():
            found = "property"
        elif "foreign" in s.lower() and "jurisdiction" in s.lower():
            found = "foreign"
        elif "legal" in s.lower() and "proceeding" in s.lower():
            found = "legal"
        elif "information" in s.lower() and "other" in s.lower():
            found = "other"
        elif "unresolved" in s.lower():
            found = "unresolved"
        elif "risk" in s.lower():
            found = "risk"
        
        # we are not going to summarize MD&A and financial notes sections of the document, while both extremely important,
        # because we didn't manage to obtain useful results from OpenAI models, without further pre-processing.
        
        # elif "management" in s.lower() and "discussion" in s.lower():
        #     found = "MD&A"
        # elif "supplementa" in s.lower() or ("note" in s.lower() and "statement" not in s.lower()):
        #     found = "notes"

        if found is not None:
            result[found]["text"] += doc["sections"][s]["text"]
            result[found]["links"].append({
                "title": s,
                "link": doc["sections"][s]["link"] if "link" in doc["sections"][s] else None
            })

    return result

def restructure_parsed_10q(doc):
    result = {
        "risk": {"text":"", "links":[]},
        "MD&A": {"text":"", "links":[]},
        "legal": {"text":"", "links":[]},
        "other": {"text":"", "links":[]},
        "equity": {"text":"", "links":[]},
        "defaults": {"text":"", "links":[]},
    }

    for s in doc["sections"]:

        found = None
        if "legal" in s.lower() and "proceeding" in s.lower():
            found = "legal"
        elif "management" in s.lower() and "discussion" in s.lower():
            found = "MD&A"
        elif "information" in s.lower() and "other" in s.lower():
            found = "other"
        elif "risk" in s.lower():
            found = "risk"
        elif "sales" in s.lower() and "equity" in s.lower():
            found = "equity"
        elif "default" in s.lower():
            found = "defaults"

        if found is not None:
            result[found]["text"] += doc["sections"][s]["text"]
            result[found]["links"].append({
                "title": s,
                "link": doc["sections"][s]["link"] if "link" in doc["sections"][s] else None
            })

    return result

def restructure_parsed_8k(doc):

    result = {}

    for s in doc["sections"]:
        if "financial statements and exhibits" in s.lower():
            continue
        result[s] = doc["sections"][s]

    return result

def sections_summary(doc, verbose=False):
    """
    Summarize all sections of a document using openAI API.
    Upsert summary on MongoDB (overwrite previous one, in case we make changes to openai_interface)

    This method is configured to use gpt-3.5-turbo. At the moment this model has two different version,
    a version with 4k token and a version with 16k tokens. The one we use is based on the length of a section.

    :param doc: a parsed_document from MongoDB
    :param verbose: passed to langchain verbose
    :return:
    """

    company = company_from_cik(doc["cik"])
    result = {"_id": doc["_id"],
              "name": company["name"],
              "ticker": company["ticker"],
              "form_type": doc["form_type"],
              "filing_date": doc["filing_date"]}

    # keep track of duration and costs
    total_cost = 0
    total_start_time = time.time()

    if "10-K" in doc["form_type"]:
        new_doc = restructure_parsed_10k(doc)
    elif "10-Q" in doc["form_type"]:
        new_doc = restructure_parsed_10q(doc)
    elif doc["form_type"] == "8-K":
        new_doc = restructure_parsed_8k(doc)
    else:
        print(f"form_type {doc['form_type']} is not yet implemented")
        return

    # for each section
    for section_title, section in new_doc.items():

        section_links = section["links"] if "links" in section else None
        section_text = section["text"]

        start_time = time.time()
        
        # if the section text is too small we skip it, it's probably not material
        if len(section_text) < 250:
            continue

        # select chain_type and model (4k or 16k) based on the section and its length
        if section_title in ["business", "risk", "MD&A"]:
            chain_type = "refine"

            if len(section_text) > 25000:
                model = "gpt-3.5-turbo-16k"
            else:
                model = "gpt-3.5-turbo"
        else:
            if len(section_text) < 25000:
                chain_type = "refine"
                model = "gpt-3.5-turbo"
            elif len(section_text) < 50000:
                chain_type = "map_reduce"
                model = "gpt-3.5-turbo"
            else:
                chain_type = "map_reduce"
                model = "gpt-3.5-turbo-16k"

        original_len = len(section_text)

        # get summary from openAI model
        print(f"{section_title} original_len: {original_len} use {model} w/ chain {chain_type}")
        summary, cost = summarize_section(section_text, model, chain_type, verbose)

        result[section_title] = {"summary":summary, "links": section_links}

        summary_len = len(''.join(summary))
        reduction = 100 - round(summary_len / original_len * 100, 2)

        total_cost += cost
        duration = round(time.time() - start_time, 1)

        print(f"{section_title} original_len: {original_len} summary_len: {summary_len} reduction: {reduction}% "
              f"cost: {cost}$ duration:{duration}s used {model} w/ chain {chain_type}")

    mongodb.upsert_document("items_summary", result)

    total_duration = round(time.time() - total_start_time, 1)

    print(f"\nTotal Cost: {total_cost}$, Total duration: {total_duration}s")