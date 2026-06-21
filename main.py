from fastmcp import FastMCP
import os
import aiosqlite
import tempfile

# Check environment variable for DB path, default to temporary directory
DB_PATH = os.getenv("EXPENSES_DB_PATH") or os.path.join(tempfile.gettempdir(), "expenses.db")
# Ensure parent directory exists
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

print(f"Database path: {DB_PATH}")

mcp = FastMCP("ExpenseTracker")

def init_db():  # Keep as sync for initialization
    try:
        # Use synchronous sqlite3 just for initialization
        import sqlite3
        with sqlite3.connect(DB_PATH) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""
                CREATE TABLE IF NOT EXISTS expenses(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                )
            """)
            # Test write access
            c.execute("INSERT OR IGNORE INTO expenses(date, amount, category) VALUES ('2000-01-01', 0, 'test')")
            c.execute("DELETE FROM expenses WHERE category = 'test'")
            print("Database initialized successfully with write access")
    except Exception as e:
        print(f"Database initialization error: {e}")
        raise

# Initialize database synchronously at module load
init_db()

@mcp.tool()
async def add_expense(date: str, amount: float, category: str, subcategory: str="", note: str="")->dict:  # Changed: added async
    '''
    Add a new expense entry to the database.
    Date should preferably be in YYYY-MM-DD format.
    Amount should be a positive number.
    '''
    try:
        async with aiosqlite.connect(DB_PATH) as c:  # Changed: added async
            if amount <= 0:
                return {
                    "status": "error",
                    "message": "Amount must be positive"
                }
            cur = await c.execute(  # Changed: added await
                "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?,?,?,?,?)",
                (date, amount, category, subcategory, note)
            )
            expense_id = cur.lastrowid
            await c.commit()  # Changed: added await
            return {
                "status": "success", 
                "id": expense_id, 
                "message": "Expense added successfully"
            }
    except Exception as e:
        if "readonly" in str(e).lower():
            return {"status": "error", "message": "Database is in read-only mode. Check file permissions."}
        return {
            "status": "error", 
            "message": f"Database error: {str(e)}"
        }
    
@mcp.tool()
async def list_expenses(start_date:str, end_date:str): 
    '''List expense entries within an inclusive date range.'''
    try:
        async with aiosqlite.connect(DB_PATH) as c:  
            cur = await c.execute( 
                """
                SELECT id, date, amount, category, subcategory, note
                FROM expenses
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC, id DESC
                """,
                (start_date, end_date)
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]  # Changed: added await
    except Exception as e:
        return {"status": "error", "message": f"Error listing expenses: {str(e)}"}

@mcp.tool()
async def summarize(start_date:str, end_date:str, category:str | None=None):  # Changed: added async
    '''Summarize expenses by category within an inclusive date range.'''
    try:
        async with aiosqlite.connect(DB_PATH) as c:  # Changed: added async
            query = """
                SELECT category, SUM(amount) AS total_amount, COUNT(*) as count
                FROM expenses
                WHERE date BETWEEN ? AND ?
            """
            params = [start_date, end_date]

            if category:
                query += " AND category = ?"
                params.append(category)

            query += " GROUP BY category ORDER BY total_amount DESC"

            cur = await c.execute(query, params)  # Changed: added await
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]  # Changed: added await
    except Exception as e:
        return {"status": "error", "message": f"Error summarizing expenses: {str(e)}"}

@mcp.tool()
async def update_expense(expense_id: int, date: str | None = None, amount: float | None = None, category: str | None = None, subcategory: str | None = None, note: str | None = None) -> dict:
    '''
    Update an existing expense entry by its ID. 
    Only the provided fields will be updated.
    '''
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
            if not await cur.fetchone():
                return {"status": "error", "message": f"Expense with ID {expense_id} not found"}
                
            updates = []
            params = []
            if date is not None:
                updates.append("date = ?")
                params.append(date)
            if amount is not None:
                if amount <= 0:
                    return {"status": "error", "message": "Amount must be positive"}
                updates.append("amount = ?")
                params.append(amount)
            if category is not None:
                updates.append("category = ?")
                params.append(category)
            if subcategory is not None:
                updates.append("subcategory = ?")
                params.append(subcategory)
            if note is not None:
                updates.append("note = ?")
                params.append(note)
                
            if not updates:
                return {"status": "error", "message": "No fields provided to update"}
                
            params.append(expense_id)
            query = f"UPDATE expenses SET {', '.join(updates)} WHERE id = ?"
            
            await c.execute(query, params)
            await c.commit()
            return {"status": "success", "message": f"Expense {expense_id} updated successfully"}
    except Exception as e:
        return {"status": "error", "message": f"Error updating expense: {str(e)}"}

@mcp.tool()
async def delete_expense(expense_id: int | None = None, date: str | None = None) -> dict:
    '''
    Delete an expense by its ID, or delete all expenses on a specific date.
    Must provide either expense_id or date.
    '''
    try:
        if expense_id is None and date is None:
            return {"status": "error", "message": "Must provide either expense_id or date"}
            
        async with aiosqlite.connect(DB_PATH) as c:
            if expense_id is not None:
                cur = await c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
                msg = f"Expense {expense_id} deleted successfully"
            else:
                cur = await c.execute("DELETE FROM expenses WHERE date = ?", (date,))
                msg = f"Expenses for date {date} deleted successfully"
                
            await c.commit()
            
            if cur.rowcount == 0:
                return {"status": "error", "message": "No matching expenses found to delete"}
                
            return {"status": "success", "message": msg, "deleted_count": cur.rowcount}
    except Exception as e:
        return {"status": "error", "message": f"Error deleting expense: {str(e)}"}

@mcp.resource("expense:///categories", mime_type="application/json")  # Changed: expense:// → expense:///
def categories():
    try:
        # Provide default categories if file doesn't exist
        default_categories = {
            "categories": [
                "Food & Dining",
                "Transportation",
                "Shopping",
                "Entertainment",
                "Bills & Utilities",
                "Healthcare",
                "Travel",
                "Education",
                "Business",
                "Other"
            ]
        }
        
        try:
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            import json
            return json.dumps(default_categories, indent=2)
    except Exception as e:
        return f'{{"error": "Could not load categories: {str(e)}"}}'

# Start the server
if __name__ == "__main__":
    # Use port 7860 as it is the default required by Hugging Face Spaces
    mcp.run(transport="http", host="0.0.0.0", port=7860) # sse
    # mcp.run()