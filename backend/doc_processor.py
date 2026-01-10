import os
import yaml
import re
import logging
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass
from PyPDF2 import PdfReader
from langchain_core.documents import Document

# Setup logging directory and configure logging
LOG_DIR = Path("backend/logs")
LOG_DIR.mkdir(exist_ok=True, parents=True)

# Standard logging setup for audit compliance
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "document_processing.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("NutriGuide-DocumentProcessor")
logger.info("Document processor initialized - safety-critical system starting")

# Metadata structure for nutrition documents
@dataclass
class DocumentMetadata:
    """Tracks critical document properties for safety and compliance"""
    source_id: str
    source_file: str
    page_number: int
    document_type: str
    topics: List[str]
    life_stages: List[str]
    contains_tables: bool
    safety_level: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary format for LangChain"""
        return {
            "source": self.source_id,
            "source_file": self.source_file,
            "page": self.page_number,
            "document_type": self.document_type,
            "topics": self.topics,
            "life_stages": self.life_stages,
            "contains_tables": self.contains_tables,
            "safety_level": self.safety_level
        }

# Core content filtering logic
class ContentFilter:
    """Filters out non-nutrition content from official documents"""
    
    # Keywords that indicate actual nutrition content
    NUTRITION_KEYWORDS = [
        'guideline', 'recommendation', 'serving', 'daily value', 'mg', 'gram',
        'sodium', 'sugar', 'fat', 'vitamin', 'mineral', 'calorie', 'dietary',
        'food group', 'vegetable', 'fruit', 'dairy', 'protein', 'grain',
        'pregnant', 'infant', 'child', 'adult', 'elderly', 'limit', 'consume',
        'adequate intake', 'tolerable upper', 'reference value', 'dietary allowance'
    ]
    
    # Patterns indicating administrative content in USDA/WHO docs
    USDA_ADMIN_PATTERNS = [
        "table of contents", "message from the secretaries", "acknowledgments",
        "appendix", "bibliography", "references", "about this edition",
        "how to use this document", "part", "chapter", "section", "figure",
        "suggested citation", "dietaryguidelines.gov", "isbn", "printed in the united states",
        "government printing office", "library of congress", "executive summary", "key recommendations", "page x", "page xi", "page xii"
    ]
    
    @staticmethod
    def is_low_value_page(text: str, page_num: int, total_pages: int, nutrition_matches: int) -> bool:
        """Skip pages with administrative content or insufficient nutrition information"""
        if not text or len(text.strip()) == 0:
            logger.debug(f"Skipping empty page {page_num}")
            return True
            
        text_lower = text.lower().strip()
        word_count = len(text_lower.split())
        
        # USDA documents put admin stuff in first 15 pages
        if page_num <= 15:
            admin_matches = sum(1 for pattern in ContentFilter.USDA_ADMIN_PATTERNS if pattern in text_lower)
            if admin_matches >= 1:
                logger.info(f"Skipping page {page_num}: administrative content ({admin_matches} matches)")
                return True
        
        # First 20 pages need decent nutrition content
        if page_num <= 20 and nutrition_matches < 3:
            logger.info(f"Skipping page {page_num}: insufficient nutrition content ({nutrition_matches} keywords)")
            return True
        
        # Table of contents detection
        if "table of contents" in text_lower and "page" in text_lower and word_count < 500:
            logger.info(f"Skipping page {page_num}: table of contents")
            return True
        
        # Copyright pages
        if ("copyright" in text_lower or "©" in text_lower) and ("reserved" in text_lower) and word_count < 300:
            logger.info(f"Skipping page {page_num}: copyright notice")
            return True
        
        return False
    
    @staticmethod
    def detect_life_stages(text: str) -> List[str]:
        """Identify life stages mentioned for targeted recommendations"""
        life_stages = set()
        text_lower = text.lower()
        
        # Pregnancy/lactation terms
        if any(term in text_lower for term in ["pregnant", "pregnancy", "maternal", "antenatal"]):
            life_stages.add("pregnant")
        if any(term in text_lower for term in ["breastfeed", "lactation", "breast milk"]):
            life_stages.add("breastfeeding")
        
        # Infant/child terms
        if any(term in text_lower for term in ["infant", "baby", "birth", "newborn", "0-12 months"]):
            life_stages.add("infants")
        if any(term in text_lower for term in ["child", "children", "adolescent", "teen", "toddler", "preschool"]):
            life_stages.add("children_teens")
        
        # Adult terms
        if any(term in text_lower for term in ["adult", "adults", "middle aged"]):
            if any(term in text_lower for term in ["older", "elderly", "senior", "65+", "aging"]):
                life_stages.add("older_adults")
            else:
                life_stages.add("adults")
        
        # Special cases
        if "athlete" in text_lower or "sports" in text_lower:
            life_stages.add("athletes")
        
        return list(life_stages) if life_stages else ["general"]

# Handles nutrient table detection
class TableProcessor:
    """Detects and marks actual nutrient recommendation tables"""
    
    @staticmethod
    def detect_nutrient_tables(text: str) -> bool:
        """Only flag real nutrient tables, ignore admin tables"""
        text_lower = text.lower()
        
        # Real nutrient table indicators
        nutrient_indicators = [
            "daily value", "dv%", "recommended intake", "adequate intake",
            "tolerable upper intake level", "ul", "ai", "rda", 
            "food sources of", "milligrams per day", "grams per day",
            "sodium recommendation", "sugar recommendation", "fat recommendation",
            "vitamin d", "calcium", "potassium", "fiber", "nutrient"
        ]
        
        # Disqualifiers (admin tables)
        non_nutrient_indicators = [
            "table of contents", "figure", "appendix", "bibliography",
            "references", "acknowledgments", "contributors", "reviewers",
            "chapter", "section", "part", "page number"
        ]
        
        nutrient_count = sum(1 for indicator in nutrient_indicators if indicator in text_lower)
        has_disqualifier = any(indicator in text_lower for indicator in non_nutrient_indicators)
        
        # Need at least 2 nutrient indicators and no disqualifiers
        return nutrient_count >= 2 and not has_disqualifier
    
    @staticmethod
    def extract_table_content(text: str) -> str:
        """Wrap real nutrient tables with markers for special handling"""
        if not TableProcessor.detect_nutrient_tables(text):
            return text
        
        return f"[NUTRIENT_TABLE_START]\n{text}\n[NUTRIENT_TABLE_END]"

# Quality validation for processed chunks
def validate_processed_chunks(documents: List[Document]) -> List[tuple]:
    """Catches chunks with admin content that slipped through filtering"""
    admin_keywords = [
        "citation", "downloaded", "publication", "printed", "isbn",
        "government printing", "congress", "copyright", "reserved",
        "acknowledgments", "funding", "contract", "prepared by",
        "submitted to", "drafted by", "suggested citation", "dietaryguidelines.gov"
    ]
    
    problematic_chunks = []
    
    for i, doc in enumerate(documents):
        text_lower = doc.page_content.lower()
        admin_count = sum(1 for kw in admin_keywords if kw in text_lower)
        nutrition_count = sum(1 for kw in ContentFilter.NUTRITION_KEYWORDS if kw in text_lower)
        word_count = len(text_lower.split())
        
        # Flag admin-heavy chunks with insufficient nutrition content
        if (admin_count >= 2 and nutrition_count < 2 and word_count < 300) or \
           ("suggested citation" in text_lower) or \
           ("dietaryguidelines.gov" in text_lower and nutrition_count < 3):
            problematic_chunks.append((
                i,
                doc.metadata['source'],
                doc.metadata['page'],
                admin_count,
                nutrition_count,
                word_count,
                doc.page_content[:150].replace('\n', ' ') + "..."
            ))
    
    return problematic_chunks

# Processes a single document
def process_single_document(entry: Dict[str, Any]) -> List[Document]:
    """Process one PDF document into clean, metadata-rich chunks"""
    file_path = Path(entry['path'])
    
    if not file_path.exists():
        raise FileNotFoundError(f"Document missing: {file_path} for {entry['id']}")
    
    logger.debug(f"Opening PDF: {file_path}")
    
    try:
        reader = PdfReader(str(file_path))
    except Exception as e:
        raise ValueError(f"PDF read error {file_path}: {str(e)}") from e
    
    total_pages = len(reader.pages)
    logger.info(f"   Document has {total_pages} pages")
    
    # Determine document type
    doc_type = "core_guideline"
    if any(keyword in entry['id'].lower() for keyword in ["nutrient", "sodium", "sugar", "fat", "vitamin"]):
        doc_type = "nutrient_specific"
    elif "summary" in entry['id'].lower() or "executive" in entry['id'].lower():
        doc_type = "summary"
    
    processed_docs = []
    valid_pages = 0
    skipped_pages = 0
    
    # Process each page
    for page_num in range(1, total_pages + 1):
        try:
            page = reader.pages[page_num - 1]
            text = page.extract_text() or ""
            text_lower = text.lower()
            
            # Calculate nutrition content density
            nutrition_matches = sum(1 for keyword in ContentFilter.NUTRITION_KEYWORDS if keyword in text_lower)
            
            # Skip low-value pages
            if ContentFilter.is_low_value_page(text, page_num, total_pages, nutrition_matches):
                skipped_pages += 1
                continue
            
            valid_pages += 1
            
            # Only detect life stages on meaningful nutrition pages
            if nutrition_matches >= 3:
                life_stages = ContentFilter.detect_life_stages(text)
            else:
                life_stages = ["general"]
            
            # Detect and mark nutrient tables
            contains_tables = TableProcessor.detect_nutrient_tables(text)
            if contains_tables:
                text = TableProcessor.extract_table_content(text)
            
            # Determine safety level
            if nutrition_matches < 3:
                safety_level = "administrative"
            else:
                safety_level = "general"
                medical_triggers = ["pregnant", "breastfeed", "infant", "medical condition", "disease", "disorder", "illness"]
                if any(trigger in text_lower for trigger in medical_triggers):
                    safety_level = "medical_caution"
                
                professional_triggers = ["professional use only", "healthcare provider", "clinician", "prescribe", "diagnose", "treat"]
                if any(trigger in text_lower for trigger in professional_triggers):
                    safety_level = "professional_use_only"
            
            # Create metadata and document
            metadata = DocumentMetadata(
                source_id=entry['id'],
                source_file=os.path.basename(file_path),
                page_number=page_num,
                document_type=doc_type,
                topics=entry.get('topics', ['general']),
                life_stages=life_stages,
                contains_tables=contains_tables,
                safety_level=safety_level
            )
            
            doc = Document(
                page_content=text,
                metadata=metadata.to_dict()
            )
            
            processed_docs.append(doc)
            
        except Exception as e:
            logger.warning(f"   Error on page {page_num} of {entry['id']}: {str(e)}")
            continue
    
    logger.info(f"   Valid pages: {valid_pages}, Skipped: {skipped_pages}")
    logger.info(f"   Created {len(processed_docs)} chunks from {entry['id']}")
    
    if len(processed_docs) == 0:
        logger.warning(f"   No valid chunks from {entry['id']} - may need manual review")
    
    return processed_docs

# Main entry point
def load_and_preprocess_documents(manifest_path: str = "manifests/corpus_manifest.yaml") -> List[Document]:
    """Load and process all documents from manifest file"""
    logger.info(f"Starting document processing from manifest: {manifest_path}")
    
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        error_msg = f"Manifest file not found: {manifest_path}"
        logger.error(error_msg)
        logger.error(f"Check structure: expected manifest in '{manifest_file.parent}'")
        raise FileNotFoundError(error_msg)
    
    try:
        with open(manifest_file, 'r', encoding='utf-8') as f:
            corpus = yaml.safe_load(f)
        logger.info(f"Loaded manifest with {len(corpus)} documents")
    except Exception as e:
        error_msg = f"Manifest load error: {str(e)}"
        logger.error(error_msg)
        logger.error("Check YAML syntax - look for indentation errors")
        raise ValueError(error_msg) from e
    
    all_documents = []
    successful_docs = 0
    failed_docs = 0
    
    for entry in corpus:
        try:
            logger.info(f"\nProcessing document: {entry['id']}")
            logger.info(f"   Source: {entry.get('source', 'Unknown')}")
            logger.info(f"   Path: {entry['path']}")
            
            doc_path = Path(entry['path'])
            if not doc_path.exists():
                logger.error(f"   Document missing: {doc_path}")
                raise FileNotFoundError(f"Missing document: {doc_path}")
            
            docs = process_single_document(entry)
            all_documents.extend(docs)
            successful_docs += 1
            logger.info(f"   Successfully processed {entry['id']}: {len(docs)} chunks")
        except Exception as e:
            failed_docs += 1
            logger.error(f"   Failed to process {entry['id']}: {str(e)}")
            logger.error(f"   Check document permissions and PDF integrity")
            continue
    
    logger.info(f"\nPRE-VALIDATION SUMMARY:")
    logger.info(f"   Successfully processed: {successful_docs}")
    logger.info(f"   Failed documents: {failed_docs}")
    logger.info(f"   Total chunks before validation: {len(all_documents)}")
    
    logger.info("\nVALIDATING CHUNK QUALITY - SAFETY CHECK")
    try:
        problematic = validate_processed_chunks(all_documents)
    except Exception as e:
        logger.error(f"VALIDATION FAILED: {str(e)}")
        logger.error("Falling back to all documents - MANUAL REVIEW REQUIRED")
        return all_documents
    
    if problematic:
        logger.warning(f"FOUND {len(problematic)} LOW-QUALITY CHUNKS WITH ADMIN CONTENT:")
        
        for idx, source, page, admin_cnt, nut_cnt, words, preview in problematic[:5]:
            logger.warning(f"   • [PAGE {page}] {source}: {admin_cnt} admin keywords, {nut_cnt} nutrition keywords")
            logger.warning(f"     Preview: \"{preview}\"")
        
        if len(problematic) > 5:
            logger.warning(f"   ... and {len(problematic)-5} more problematic chunks")
        
        # Remove bad chunks
        indices_to_remove = {chunk[0] for chunk in problematic}
        cleaned_documents = [
            doc for i, doc in enumerate(all_documents) 
            if i not in indices_to_remove
        ]
        
        logger.warning(f"AUTOMATICALLY REMOVED {len(problematic)} LOW-QUALITY CHUNKS")
        logger.warning(f"CLEANED DOCUMENT COUNT: {len(cleaned_documents)} chunks ({len(all_documents)-len(cleaned_documents)} removed)")
        
        # Safety net - never return empty set
        if not cleaned_documents:
            logger.error("CRITICAL ERROR: All chunks removed during validation!")
            logger.error("MANUAL INTERVENTION REQUIRED: Check document filtering logic")
            raise ValueError("No valid chunks remained after validation - safety compromised")
        
        return cleaned_documents
    else:
        logger.info("ALL CHUNKS CONTAIN NUTRITION-RELEVANT CONTENT - VALIDATION PASSED")
        return all_documents

# Test execution when run directly
if __name__ == "__main__":
    """Run validation mode to test document processing pipeline"""
    print("=" * 60)
    print("NUTRIGUIDE DOCUMENT PROCESSOR - VALIDATION MODE")
    print("=" * 60)
    
    try:
        documents = load_and_preprocess_documents("manifests/corpus_manifest.yaml")
        
        print(f"\nPROCESSING SUCCESSFUL!")
        print(f"Total chunks created: {len(documents)}")
        
        # Count chunks by type
        doc_type_counts = {}
        for doc in documents:
            doc_type = doc.metadata['document_type']
            doc_type_counts[doc_type] = doc_type_counts.get(doc_type, 0) + 1
        
        print("\nDocument type distribution:")
        for doc_type, count in doc_type_counts.items():
            print(f"   • {doc_type}: {count} chunks")
        
        # Show sample chunk
        if documents:
            print(f"\nSAMPLE CHUNK ANALYSIS (first chunk):")
            print(f"   Source ID: {documents[0].metadata['source']}")
            print(f"   File: {documents[0].metadata['source_file']}")
            print(f"   Page: {documents[0].metadata['page']}")
            print(f"   Document Type: {documents[0].metadata['document_type']}")
            print(f"   Life Stages: {', '.join(documents[0].metadata['life_stages'])}")
            print(f"   Safety Level: {documents[0].metadata['safety_level']}")
            print(f"   Contains Tables: {'Yes' if documents[0].metadata['contains_tables'] else 'No'}")
            
            preview = documents[0].page_content[:200].replace('\n', ' ')
            print(f"   Content Preview: \"{preview}...\"")
        
        # Safety check
        safety_check = all('safety_level' in doc.metadata for doc in documents)
        print(f"\nSAFETY METADATA VALIDATION: {'PASSED' if safety_check else 'FAILED'}")
        
        # Save sample output
        if documents:
            sample_file = LOG_DIR / "sample_processed_content.txt"
            with open(sample_file, "w", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write("NUTRIGUIDE SAMPLE PROCESSED CONTENT\n")
                f.write("=" * 60 + "\n\n")
                f.write(f"Source: {documents[0].metadata['source']}\n")
                f.write(f"File: {documents[0].metadata['source_file']}\n")
                f.write(f"Page: {documents[0].metadata['page']}\n")
                f.write(f"Document Type: {documents[0].metadata['document_type']}\n")
                f.write(f"Life Stages: {', '.join(documents[0].metadata['life_stages'])}\n")
                f.write(f"Safety Level: {documents[0].metadata['safety_level']}\n")
                f.write(f"Contains Tables: {documents[0].metadata['contains_tables']}\n\n")
                f.write("=" * 60 + "\n")
                f.write("CONTENT PREVIEW:\n")
                f.write("=" * 60 + "\n\n")
                f.write(documents[0].page_content[:1000] + "...\n")
            print(f"\nSample output saved to: {sample_file}")
        
        print(f"\nVALIDATION COMPLETE - SYSTEM READY FOR NEXT STEPS")
        print(f"   • Total chunks processed: {len(documents)}")
        print(f"   • Safety metadata: {'Present' if safety_check else 'Missing'}")
        print(f"   • Sample output: {sample_file}")
        
    except Exception as e:
        print(f"\nPROCESSING FAILED: {str(e)}")
        print("Check:")
        print("   • manifests/corpus_manifest.yaml exists and is valid")
        print("   • All document paths in manifest are correct")
        print("   • PDF files are not corrupted")
        print(f"   • Log file: {LOG_DIR / 'document_processing.log'}")
        exit(1)
    
    print("\n" + "=" * 60)
    print("NUTRIGUIDE DOCUMENT PROCESSOR - READY FOR INTEGRATION")
    print("=" * 60)