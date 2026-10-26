import os

pub_dois_file = 'C:/Users/20155/dpa4_project/data/pub_dois.txt'
pdf_dois_file = 'C:/Users/20155/dpa4_project/data/pdf_dois.txt'

if not os.path.exists(pub_dois_file):
    print("❌ 找不到 pub_dois.txt")
else:
    with open(pub_dois_file, 'r') as f:
        pub_dois = set([line.strip() for line in f if line.strip()])

pdf_files = os.listdir('C:/Users/20155/dpa4_project/data/pdfs')
pdf_dois = set([f.replace('.pdf', '').replace('_', '/') for f in pdf_files if f.endswith('.pdf')])

intersection = pub_dois & pdf_dois

print(f"图谱 Publication: {len(pub_dois)}")
print(f"PDF 文件: {len(pdf_files)}")
print(f"重合: {len(intersection)}")
print("\n重合的 DOI:")
for doi in sorted(intersection):
    print(doi)