# Ebay Price Tracker

An automation script that scans through eBays search results of a given item, and tracks the average price of the item over a specified period of time. The script scrapes the price of the item from the first page of search results on eBay, and exports the average to a .csv file in the same directory.

Preview: 
<img width="948" alt="Screenshot 2025-04-12 at 6 40 08 PM" src="https://github.com/user-attachments/assets/04169a9c-4a68-4324-a917-aeec97598cbe" />
<img width="1043" alt="Screenshot 2025-04-13 at 12 09 29 PM" src="https://github.com/user-attachments/assets/1971c22a-3859-41a2-b5ec-b08261b46784" />
<img width="1043" alt="Screenshot 2025-04-13 at 12 09 57 PM" src="https://github.com/user-attachments/assets/536a602a-c63c-4260-8bc7-de9ea572fe52" />
<img width="934" alt="Screenshot 2025-04-24 at 8 05 29 PM" src="https://github.com/user-attachments/assets/9425b8d9-0d4f-4c45-8224-854a882aa8d4" />
<img width="934" alt="Screenshot 2025-04-24 at 8 06 06 PM" src="https://github.com/user-attachments/assets/674b6c2a-5851-464a-b44d-030be13808d9" />

## How to Run the Script

1. **Install Dependencies**:
   Ensure you have Python installed on your system. Install the required dependencies by running:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Script**:
   Execute the script using the following command:
   ```bash
   python main.py <item_name>
   ```
   Replace `<item_name>` with the name of the item you want to track. For example:
   ```bash
   python main.py "nintendo switch 2"
   ```

3. **Provide a Link (Optional)**:
   If you do not provide an item name, the script will prompt you to enter an eBay search URL manually.

4. **Output**:
   The script will calculate the average price of the item and save it to `prices.csv` in the same directory.
