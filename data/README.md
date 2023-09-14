## **Dataset**

- ***Visual Dataset***  
AI-Hub '한국인 감정인식을 위한 복합영상' 활용

```
.  
├── images   # 이미지 경로  
│   ├── {uid}_{gender}_{age}_{emotion}_{upload_id}.(jpg|jpeg)      
│   └── ...                
└── annotations         
    ├── sample_train/   # Temp files 
    ├── sample_val/     
    ├── train.json      # Annotation + Prompt for ChatGPT
    ├── val.json                           
    ├── train.parquet   # Annotation + Prompt + Generated TOD by ChatGPT
    └── val.parquet                    
```