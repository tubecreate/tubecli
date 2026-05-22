import json
import os

def main():
    script_path = r"c:\tubecreate-vue\tubecli\data\edu_video_studio\projects\4e93bff6\lessons\lesson_b7f544\lesson_script.json"
    
    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    updated_count = 0
    for step in data.get("steps", []):
        for el in step.get("elements", []):
            if el.get("type") == "custom_js" and "code" in el:
                code = el["code"]
                original = code
                
                # Replace single quoted static fonts
                code = code.replace("'24px sans-serif'", "'24px ' + T.font")
                code = code.replace("'36px sans-serif'", "'36px ' + T.font")
                code = code.replace("'34px sans-serif'", "'34px ' + T.font")
                code = code.replace("'40px sans-serif'", "'40px ' + T.font")
                code = code.replace("'12px sans-serif'", "'12px ' + T.font")
                
                # Replace template literal dynamic fonts
                code = code.replace("px sans-serif`", "px ${T.font}`")
                
                if code != original:
                    el["code"] = code
                    updated_count += 1
                    
    if updated_count > 0:
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Successfully updated {updated_count} custom_js blocks in lesson_script.json.")
    else:
        print("No updates needed or no matching sans-serif instances found.")

if __name__ == "__main__":
    main()
