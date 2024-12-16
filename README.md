# Financial Data Analytics Platform

## Overview
The Financial Data Analytics Platform leverages data science and machine learning to analyze sectoral financial trends using data from the SEC EDGAR database. This project demonstrates how to transform raw financial data into actionable insights for stakeholders such as investors, policymakers, and business leaders.

## Key Features
- **Advanced Data Processing**: Automates data curation and storage using Python and MongoDB.
- **Interactive Dashboards**: Visualizes insights with Tableau, highlighting trends, profitability, and risks.
- **Machine Learning Models**: Implements predictive analysis to forecast market trends and evaluate company performance.
- **Summarization with LLMs**: Uses OpenAI GPT models for summarizing complex 10-K filings.

## Objectives
1. Analyze financial data trends across sectors (e.g., Technology, Finance, Healthcare).
2. Identify correlations between profitability, risk, and research investments.
3. Present insights through interactive visualizations and dashboards.

## Data Source
- **SEC EDGAR Database**: Financial filings of publicly traded U.S. companies.

### Key Metrics Analyzed
- **Assets and Liabilities**
- **Profit and Loss**
- **Research and Development (R&D) Expenditure**
- **Sector-wise Trends**

## Methodology
1. **Data Collection**:
   - Extract financial data using Python scripts via the SEC EDGAR API.
   - Store data in MongoDB for scalable storage.

2. **Data Processing**:
   - Clean and preprocess data to handle missing values and standardize formats.
   - Engineer features like Asset-to-Liability Ratio and R&D-to-Profit Ratio.

3. **Visualization**:
   - Create dashboards using Tableau for insights on sectoral performance, profitability, and risk.

4. **Machine Learning**:
   - Train predictive models for market analysis.
   - Validate trends with statistical tests and correlation analyses.

5. **Summarization with LLMs**:
   - Automate the extraction and summarization of 10-K filings using OpenAI GPT models.

## Tools and Technologies
- **Programming Languages**: Python
- **Database**: MongoDB
- **Visualization**: Tableau
- **Libraries**: pandas, BeautifulSoup, LangChain
- **APIs**: SEC EDGAR API
- **Machine Learning**: Random Forest, Statistical Testing

## Visualizations
1. **Asset-Liability Trends**: Tracks growth from 2009 to 2024.
2. **Sector-wise Profitability**: Highlights high-performing and struggling sectors.
3. **R&D vs. Profit**: Shows correlation between research investment and profitability.
4. **Interactive Dashboards**: Enables real-time filtering and dynamic insights.

## Key Insights
- **Technology Sector**: Dominates profitability with high R&D investment.
- **Consumer Discretionary**: Faces significant financial risks despite high expenses.
- **Financial Stability**: High asset-to-liability ratios indicate robust performance.

## Ethical Considerations
- **Bias Mitigation**: Normalized data across sectors to ensure fair comparisons.
- **Transparency**: Documented all preprocessing and modeling steps.
- **Reproducibility**: Publicly available code and datasets.

## How to Run the Project
1. Clone the repository:
   ```bash
   git clone https://github.com/madhurlak0810/SEC-edgar.git
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the data extraction and preprocessing pipeline:
   ```bash
   python data_pipeline.py
   ```
4. Visualize the insights with Tableau or view pre-generated dashboards.

## Contributions
- **Madhur Lakshmanan**: Data curation, preprocessing, and MongoDB integration and OpenAI integration.
- **Inesh Tandon**: Machine learning model design and performance validation.
- **Rohan Jain**: Visualization and result analysis.
- **Balamurugan**: Visualization and documentation.
- **Abhyansh Anand**: Report creation and sectoral analysis.


## Contact
For questions or suggestions, please contact [Madhur Lakshmanan](mailto:madhulak@umd.edu).

---

