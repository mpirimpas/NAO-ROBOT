import os
from flask import Flask, request, jsonify
import google.generativeai as genai

# Αρχικοποίηση Flask app
app = Flask(__name__)

# Ρύθμιση του API key για το Gemini (αντικατάστησε με το δικό σου API Key)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY"))

# Αρχικοποίηση του μοντέλου Gemini
model = genai.GenerativeModel('gemini-2.0-flash')

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json(force=True, silent=True)
        
        if not data or 'prompt' not in data:
            return jsonify({"response": "Δεν έλαβα κάποιο μήνυμα."}), 400
        
        user_prompt = data.get('prompt', '').strip()
        
        if not user_prompt:
            return jsonify({"response": "Το μήνυμα ήταν κενό."}), 400
        
        print("Έλαβα από NAO:", user_prompt)

        # Αποστολή στο Gemini API
        gemini_response = model.generate_content(user_prompt)
        reply_text = gemini_response.text

        print("Απάντηση Gemini:", reply_text)

        return jsonify({"response": reply_text})

    except Exception as e:
        print("Σφάλμα στον Server:", str(e))
        return jsonify({"response": "Προέκυψε εσωτερικό σφάλμα στον server."}), 500

if __name__ == '__main__':
    # Ανοίγει σε όλες τις διεπαφές (0.0.0.0) στη θύρα 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
