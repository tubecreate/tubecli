"""Update Google Search skill in skills.json to use web_search + model_agent"""
import json

with open('data/skills.json', 'r', encoding='utf-8') as f:
    skills = json.load(f)

for i, s in enumerate(skills):
    if 'Google Search' in s.get('name', ''):
        skills[i]['name'] = '🔍 Google Search'
        skills[i]['commands'] = ['google search', 'tìm kiếm google', 'search google', 'tìm google']
        skills[i]['description'] = 'Tìm kiếm Google nhanh bằng HTTP + AI tóm tắt kết quả. Không cần mở browser.'
        skills[i]['workflow_data'] = {
            'name': 'Google Search',
            'nodes': [
                {
                    'id': 'search_query',
                    'type': 'text_input',
                    'label': 'Từ khóa tìm kiếm',
                    'config': {'text': ''},
                },
                {
                    'id': 'web_search',
                    'type': 'web_search',
                    'label': 'Google Search (HTTP)',
                    'config': {},
                },
                {
                    'id': 'ai_summarize',
                    'type': 'model_agent',
                    'label': 'AI Tóm tắt',
                    'config': {
                        'provider': 'auto',
                        'system_prompt': 'Bạn là trợ lý AI. Người dùng đã tìm kiếm Google, dưới đây là kết quả. Hãy tóm tắt ngắn gọn, rõ ràng bằng ngôn ngữ của người dùng. Nếu có thông tin thời tiết, tin tức, hoặc dữ liệu cụ thể, hãy trình bày rõ ràng. Trả lời tự nhiên, thân thiện.',
                        'max_tokens': 1024,
                        'temperature': 0.5,
                    },
                },
                {
                    'id': 'result_output',
                    'type': 'output',
                    'label': 'Kết quả',
                    'config': {'print': True},
                },
            ],
            'connections': [
                {
                    'from_node_id': 'search_query',
                    'from_port_id': 'content',
                    'to_node_id': 'web_search',
                    'to_port_id': 'query',
                },
                {
                    'from_node_id': 'web_search',
                    'from_port_id': 'results',
                    'to_node_id': 'ai_summarize',
                    'to_port_id': 'prompt',
                },
                {
                    'from_node_id': 'ai_summarize',
                    'from_port_id': 'response',
                    'to_node_id': 'result_output',
                    'to_port_id': 'data',
                },
            ],
        }
        print(f'Updated: {skills[i]["name"]}')
        break
else:
    print('Google Search skill not found!')

with open('data/skills.json', 'w', encoding='utf-8') as f:
    json.dump(skills, f, indent=2, ensure_ascii=False)

print('Done!')
