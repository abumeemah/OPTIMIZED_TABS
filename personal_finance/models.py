from datetime import datetime
from pymongo import ASCENDING, DESCENDING
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError, WriteError
from translations import trans
from utils import get_mongo_db, logger
from werkzeug.security import generate_password_hash
from functools import lru_cache
import uuid

def get_db():
    """
    Get MongoDB database connection using the global client from utils.py.
    
    Returns:
        Database object
    """
    try:
        db = get_mongo_db()
        logger.info(f"Successfully connected to MongoDB database: {db.name}", extra={'session_id': 'no-session-id'})
        return db
    except Exception as e:
        logger.error(f"Error connecting to database: {str(e)}", exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def initialize_app_data(app):
    """
    Initialize MongoDB collections and indexes for bill, shopping, and budget-related collections.
    
    Args:
        app: Flask application instance
    """
    with app.app_context():
        try:
            db = get_db()
            db.command('ping')
            logger.info(f"{trans('general_database_connection_established', default='MongoDB connection established')}",
                        extra={'session_id': 'no-session-id'})
            
            collections = db.list_collection_names()
            
            # Define collection schemas for bill, shopping, and budget
            collection_schemas = {
                'users': {
                    'validator': {
                        '$jsonSchema': {
                            'bsonType': 'object',
                            'properties': {
                                '_id': {'bsonType': 'string'},
                                'user_id': {'bsonType': 'string'},
                                'ficore_credit_balance': {'bsonType': 'double': 'int': 'minimum': 0}
                            }
                        }
                    },
                    'indexes': [
                        {'key': [('user_id', ASCENDING)], 'unique': True}
                    ]
                },
                'shopping_items': {
                    'validator': {
                        '$jsonSchema': {
                            'bsonType': 'object',
                            'required': ['user_id', 'list_id', 'name', 'quantity', 'price', 'category', 'status', 'created_at', 'updated_at', 'unit'],
                            'properties': {
                                'user_id': {'bsonType': 'string'},
                                'session_id': {'bsonType': ['string', 'null']},
                                'list_id': {'bsonType': 'string'},
                                'name': {'bsonType': 'string'},
                                'quantity': {'bsonType': 'int', 'minimum': 1, 'maximum': 1000},
                                'price': {'bsonType': 'double', 'minimum': 0, 'maximum': 1000000},
                                'category': {'enum': ['fruits', 'vegetables', 'dairy', 'meat', 'grains', 'beverages', 'household', 'other']},
                                'status': {'enum': ['to_buy', 'bought']},
                                'created_at': {'bsonType': 'date'},
                                'updated_at': {'bsonType': 'date'},
                                'store': {'bsonType': ['string', 'null']},
                                'frequency': {'bsonType': 'int', 'minimum': 1, 'maximum': 365},
                                'unit': {'bsonType': 'string', 'enum': ['piece', 'carton', 'kg', 'liter', 'pack', 'other']}
                            }
                        }
                    },
                    'indexes': [
                        {'key': [('user_id', ASCENDING), ('list_id', ASCENDING)]},
                        {'key': [('created_at', DESCENDING)]}
                    ]
                },
                'shopping_lists': {
                    'validator': {
                        '$jsonSchema': {
                            'bsonType': 'object',
                            'required': ['user_id', 'name', 'budget', 'created_at', 'updated_at', 'total_spent', 'status', 'collaborators'],
                            'properties': {
                                'name': {'bsonType': 'string'},
                                'user_id': {'bsonType': 'string'},
                                'session_id': {'bsonType': ['string', 'null']},
                                'budget': {'bsonType': 'double', 'minimum': 0.01, 'maximum': 10000000000},
                                'created_at': {'bsonType': 'date'},
                                'updated_at': {'bsonType': 'date'},
                                'collaborators': {
                                    'bsonType': 'array',
                                    'items': {'bsonType': 'string'}
                                },
                                'total_spent': {'bsonType': 'double', 'minimum': 0},
                                'status': {'enum': ['active', 'saved']}
                            }
                        }
                    },
                    'indexes': [
                        {'key': [('user_id', ASCENDING), ('status', ASCENDING), ('updated_at', DESCENDING)]}
                    ]
                },
                'budgets': {
                    'validator': {
                        '$jsonSchema': {
                            'bsonType': 'object',
                            'required': ['user_id', 'income', 'fixed_expenses', 'variable_expenses', 'created_at'],
                            'properties': {
                                'user_id': {'bsonType': 'string'},
                                'session_id': {'bsonType': ['string', 'null']},
                                'income': {'bsonType': 'double', 'minimum': 0},
                                'fixed_expenses': {'bsonType': 'double', 'minimum': 0},
                                'variable_expenses': {'bsonType': 'double', 'minimum': 0},
                                'savings_goal': {'bsonType': 'double', 'minimum': 0},
                                'surplus_deficit': {'bsonType': 'double'},
                                'housing': {'bsonType': 'double', 'minimum': 0},
                                'food': {'bsonType': 'double', 'minimum': 0},
                                'transport': {'bsonType': 'double', 'minimum': 0},
                                'dependents': {'bsonType': ['int', 'double'], 'minimum': 0},
                                'miscellaneous': {'bsonType': 'double', 'minimum': 0},
                                'others': {'bsonType': 'double', 'minimum': 0},
                                'custom_categories': {
                                    'bsonType': 'array',
                                    'items': {
                                        'bsonType': 'object',
                                        'required': ['name', 'amount'],
                                        'properties': {
                                            'name': {'bsonType': 'string', 'maxLength': 50},
                                            'amount': {'bsonType': 'double', 'minimum': 0, 'maximum': 10000000000}
                                        },
                                        'additionalProperties': False
                                    },
                                    'maxItems': 20
                                },
                                'created_at': {'bsonType': 'date'}
                            }
                        }
                    },
                    'indexes': [
                        {'key': [('user_id', ASCENDING), ('created_at', DESCENDING)]}
                    ]
                },
                'bills': {
                    'validator': {
                        '$jsonSchema': {
                            'bsonType': 'object',
                            'required': ['user_id', 'bill_name', 'amount', 'due_date', 'status'],
                            'properties': {
                                'user_id': {'bsonType': 'string'},
                                'session_id': {'bsonType': ['string', 'null']},
                                'bill_name': {'bsonType': 'string'},
                                'amount': {'bsonType': 'double', 'minimum': 0},
                                'due_date': {'bsonType': 'date'},
                                'frequency': {'bsonType': ['string', 'null']},
                                'category': {'bsonType': ['string', 'null']},
                                'status': {'enum': ['pending', 'paid', 'overdue']},
                                'send_notifications': {'bsonType': 'bool'},
                                'send_email': {'bsonType': 'bool'},
                                'send_sms': {'bsonType': 'bool'},
                                'send_whatsapp': {'bsonType': 'bool'},
                                'reminder_days': {'bsonType': ['int', 'null']},
                                'user_email': {'bsonType': ['string', 'null']},
                                'user_phone': {'bsonType': ['string', 'null']},
                                'first_name': {'bsonType': ['string', 'null']}
                            }
                        }
                    },
                    'indexes': [
                        {'key': [('user_id', ASCENDING), ('due_date', ASCENDING)]},
                        {'key': [('status', ASCENDING)]}
                    ]
                },
                'bill_reminders': {
                    'validator': {
                        '$jsonSchema': {
                            'bsonType': 'object',
                            'required': ['user_id', 'notification_id', 'type', 'message', 'sent_at'],
                            'properties': {
                                'user_id': {'bsonType': 'string'},
                                'session_id': {'bsonType': ['string', 'null']},
                                'notification_id': {'bsonType': 'string'},
                                'type': {'enum': ['email', 'sms', 'whatsapp']},
                                'message': {'bsonType': 'string'},
                                'sent_at': {'bsonType': 'date'},
                                'read_status': {'bsonType': 'bool'}
                            }
                        }
                    },
                    'indexes': [
                        {'key': [('user_id', ASCENDING), ('sent_at', DESCENDING)]}
                    ]
                },
                'ficore_credit_transactions': {
                    'validator': {
                        '$jsonSchema': {
                            'bsonType': 'object',
                            'required': ['user_id', 'action', 'amount', 'timestamp', 'session_id', 'status'],
                            'properties': {
                                'user_id': {'bsonType': 'string'},
                                'action': {'bsonType': 'string'},
                                'amount': {'bsonType': 'double'},
                                'item_id': {'bsonType': ['string', 'null']},
                                'budget_id': {'bsonType': ['string', 'null']},
                                'timestamp': {'bsonType': 'date'},
                                'session_id': {'bsonType': 'string'},
                                'status': {'enum': ['completed', 'failed', 'pending']}
                            }
                        }
                    },
                    'indexes': [
                        {'key': [('user_id', ASCENDING), ('timestamp', DESCENDING)]},
                        {'key': [('status', ASCENDING)]},
                        {'key': [('action', ASCENDING)]}
                    ]
                }
            }
                
            # Initialize collections and indexes
            for collection_name, config in collection_schemas.items():
                if collection_name in collections:
                    try:
                        db.command('collMod', collection_name, validator=config.get('validator', {}))
                        logger.info(f"Updated validator for collection: {collection_name}",
                                    extra={'session_id': 'no-session-id'})
                    except OperationFailure as e:
                        logger.warning(f"Could not update validator for collection {collection_name}: {e}.")
                    except Exception as e:
                        logger.error(f"Failed to update validator for collection {collection_name}: {str(e)}",
                                     exc_info=True, extra={'session_id': 'no-session-id'})
                        raise
                else:
                    try:
                        db.create_collection(collection_name, validator=config.get('validator', {}))
                        logger.info(f"{trans('general_collection_created', default='Created collection')}: {collection_name}",
                                   extra={'session_id': 'no-session-id'})
                    except Exception as e:
                        logger.error(f"Failed to create collection {collection_name}: {str(e)}",
                                     exc_info=True, extra={'session_id': 'no-session-id'})
                        raise
                
                # Manage indexes
                existing_indexes = db[collection_name].index_information()
                for index in config.get('indexes', []):
                    keys = index['key']
                    options = {k: v for k, v in index.items() if k != 'key'}
                    
                    # Check if an index with these keys and options already exists
                    index_found = False
                    for existing_index_name, existing_index_info in existing_indexes.items():
                        if tuple(existing_index_info['key']) == tuple(keys):
                            existing_options = {k: v for k, v in existing_index_info.items() if k not in ['key', 'v', 'ns', 'name']}
                            if existing_options == options:
                                logger.info(f"Index already exists on {collection_name}: {keys}", extra={'session_id': 'no-session-id'})
                                index_found = True
                                break
                            else:
                                if existing_index_name != '_id_':
                                    logger.warning(f"Dropping conflicting index {existing_index_name} on {collection_name} to create new one.")
                                    db[collection_name].drop_index(existing_index_name)
                    
                    if not index_found:
                        try:
                            index_name = options.get('name', None)
                            db[collection_name].create_index(keys, name=index_name, **options)
                            logger.info(f"Created index on {collection_name}: {keys} with options {options}",
                                        extra={'session_id': 'no-session-id'})
                        except DuplicateKeyError:
                            logger.error(f"Failed to create UNIQUE index on {collection_name} due to existing duplicate data. "
                                         f"Please clean up duplicates manually.",
                                         extra={'session_id': 'no-session-id'})
                        except PyMongoError as e:
                            logger.error(f"Failed to create index on {collection_name}: {str(e)}",
                                         exc_info=True, extra={'session_id': 'no-session-id'})
                            raise
                            
        except Exception as e:
            logger.error(f"{trans('general_database_initialization_failed', default='Failed to initialize database')}: {str(e)}",
                         exc_info=True, extra={'session_id': 'no-session-id'})
            raise

def get_budgets(db, filter_kwargs):
    """
    Retrieve budget records based on filter criteria.
    
    Args:
        db: MongoDB database instance
        filter_kwargs: Dictionary of filter criteria
    
    Returns:
        list: List of budget records
    """
    try:
        return list(db.budgets.find(filter_kwargs).sort('created_at', DESCENDING))
    except Exception as e:
        logger.error(f"{trans('general_budgets_fetch_error', default='Error getting budgets')}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def get_bills(db, filter_kwargs):
    """
    Retrieve bill records based on filter criteria.
    
    Args:
        db: MongoDB database instance
        filter_kwargs: Dictionary of filter criteria
    
    Returns:
        list: List of bill records
    """
    try:
        return list(db.bills.find(filter_kwargs).sort('due_date', ASCENDING))
    except Exception as e:
        logger.error(f"{trans('general_bills_fetch_error', default='Error getting bills')}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def create_budget(db, budget_data):
    """
    Create a new budget record in the budgets collection.
    
    Args:
        db: MongoDB database instance
        budget_data: Dictionary containing budget information
    
    Returns:
        str: ID of the created budget record
    """
    try:
        required_fields = ['user_id', 'income', 'fixed_expenses', 'variable_expenses', 'created_at']
        if not all(field in budget_data for field in required_fields):
            raise ValueError(trans('general_missing_budget_fields', default='Missing required budget fields'))
        logger.debug(f"Inserting budget_data into {db.budgets.name}: {budget_data}", 
                     extra={'session_id': budget_data.get('session_id', 'no-session-id')})
        result = db.budgets.insert_one(budget_data)
        logger.info(f"{trans('general_budget_created', default='Created budget record with ID')}: {result.inserted_id}", 
                    extra={'session_id': budget_data.get('session_id', 'no-session-id')})
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"WriteError creating budget record: {str(e)}", 
                     exc_info=True, extra={'session_id': budget_data.get('session_id', 'no-session-id')})
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating budget record: {str(e)}", 
                     exc_info=True, extra={'session_id': budget_data.get('session_id', 'no-session-id')})
        raise

def create_bill(db, bill_data):
    """
    Create a new bill record in the bills collection.
    
    Args:
        db: MongoDB database instance
        bill_data: Dictionary containing bill information
    
    Returns:
        str: ID of the created bill record
    
    Raises:
        ValueError: If required fields are missing, due_date is not a datetime object, or status is invalid
        WriteError: If MongoDB write operation fails
        Exception: For other unexpected errors
    """
    try:
        required_fields = ['user_id', 'bill_name', 'amount', 'due_date', 'status']
        if not all(field in bill_data for field in required_fields):
            raise ValueError(trans('general_missing_bill_fields', default='Missing required bill fields'))
        
        # Validate due_date is a datetime object
        if not isinstance(bill_data['due_date'], datetime):
            raise ValueError(trans('bill_due_date_invalid_type', default='Due date must be a datetime object'))
        
        # Validate status is one of the allowed values
        valid_statuses = ['pending', 'paid', 'overdue']
        if bill_data['status'] not in valid_statuses:
            raise ValueError(trans('bill_status_invalid', default=f"Status must be one of: {', '.join(valid_statuses)}"))
        
        # Ensure amount is a float or int
        if not isinstance(bill_data['amount'], (int, float)) or bill_data['amount'] < 0:
            raise ValueError(trans('bill_amount_invalid', default='Amount must be a non-negative number'))
        
        result = db.bills.insert_one(bill_data)
        logger.info(f"{trans('general_bill_created', default='Created bill record with ID')}: {result.inserted_id}", 
                   extra={'session_id': bill_data.get('session_id', 'no-session-id')})
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"{trans('general_bill_creation_error', default='Error creating bill record')}: {str(e)}", 
                     exc_info=True, extra={'session_id': bill_data.get('session_id', 'no-session-id')})
        raise
    except ValueError as e:
        logger.error(f"{trans('general_bill_creation_error', default='Error creating bill record')}: {str(e)}", 
                     exc_info=True, extra={'session_id': bill_data.get('session_id', 'no-session-id')})
        raise
    except Exception as e:
        logger.error(f"{trans('general_bill_creation_error', default='Error creating bill record')}: {str(e)}", 
                     exc_info=True, extra={'session_id': bill_data.get('session_id', 'no-session-id')})
        raise

def create_bill_reminder(db, reminder_data):
    """
    Create a new bill reminder in the bill_reminders collection.
    
    Args:
        db: MongoDB database instance
        reminder_data: Dictionary containing bill reminder information
    
    Returns:
        str: ID of the created bill reminder
    """
    try:
        required_fields = ['user_id', 'notification_id', 'type', 'message', 'sent_at']
        if not all(field in reminder_data for field in required_fields):
            raise ValueError(trans('general_missing_bill_reminder_fields', default='Missing required bill reminder fields'))
        result = db.bill_reminders.insert_one(reminder_data)
        logger.info(f"{trans('general_bill_reminder_created', default='Created bill reminder with ID')}: {result.inserted_id}", 
                   extra={'session_id': reminder_data.get('session_id', 'no-session-id')})
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"{trans('general_bill_reminder_creation_error', default='Error creating bill reminder')}: {str(e)}", 
                     exc_info=True, extra={'session_id': reminder_data.get('session_id', 'no-session-id')})
        raise
    except Exception as e:
        logger.error(f"{trans('general_bill_reminder_creation_error', default='Error creating bill reminder')}: {str(e)}", 
                     exc_info=True, extra={'session_id': reminder_data.get('session_id', 'no-session-id')})
        raise

def create_shopping_item(db, item_data, mongo_session=None):
    """
    Create a new shopping item in the shopping_items collection.
    
    Args:
        db: MongoDB database instance
        item_data: Dictionary containing shopping item information
        mongo_session: Optional MongoDB session for transaction handling
    
    Returns:
        str: ID of the created shopping item
    """
    try:
        required_fields = ['user_id', 'list_id', 'name', 'quantity', 'price', 'category', 'status', 'created_at', 'updated_at']
        if not all(field in item_data for field in required_fields):
            raise ValueError(trans('general_missing_shopping_item_fields', default='Missing required shopping item fields'))
        item_data['unit'] = item_data.get('unit', 'piece')
        if 'session_id' in item_data and item_data['session_id']:
            item_data['session_id'] = str(item_data['session_id'])  # Ensure session_id is a string if provided
        result = db.shopping_items.insert_one(item_data, session=mongo_session)
        logger.info(f"{trans('general_shopping_item_created', default='Created shopping item with ID')}: {result.inserted_id}", 
                   extra={'session_id': item_data.get('session_id', 'no-session-id')})
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"{trans('general_shopping_item_creation_error', default='Error creating shopping item')}: {str(e)}", 
                     exc_info=True, extra={'session_id': item_data.get('session_id', 'no-session-id')})
        raise
    except Exception as e:
        logger.error(f"{trans('general_shopping_item_creation_error', default='Error creating shopping item')}: {str(e)}", 
                     exc_info=True, extra={'session_id': item_data.get('session_id', 'no-session-id')})
        raise
        
def get_shopping_items(db, filter_kwargs):
    """
    Retrieve shopping item records based on filter criteria.
    
    Args:
        db: MongoDB database instance
        filter_kwargs: Dictionary of filter criteria
    
    Returns:
        list: List of shopping item records
    """
    try:
        return list(db.shopping_items.find(filter_kwargs).sort('created_at', DESCENDING))
    except Exception as e:
        logger.error(f"{trans('general_shopping_items_fetch_error', default='Error getting shopping items')}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def to_dict_shopping_item(record):
    """Convert shopping item record to dictionary."""
    if not record:
        return {'name': None, 'quantity': None}
    return {
        'id': str(record.get('_id', '')),
        'user_id': record.get('user_id', ''),
        'session_id': record.get('session_id', ''),
        'list_id': record.get('list_id', ''),
        'name': record.get('name', ''),
        'quantity': record.get('quantity', 0),
        'price': record.get('price', 0.0),
        'category': record.get('category', ''),
        'status': record.get('status', ''),
        'created_at': record.get('created_at'),
        'updated_at': record.get('updated_at'),
        'store': record.get('store', ''),
        'frequency': record.get('frequency', 1),
        'unit': record.get('unit', 'piece')
    }

def update_shopping_item(db, item_id, update_data):
    """
    Update a shopping item in the shopping_items collection.
    
    Args:
        db: MongoDB database instance
        item_id: The ID of the shopping item to update
        update_data: Dictionary containing fields to update
    
    Returns:
        bool: True if updated, False if not found or no changes made
    """
    try:
        update_data['updated_at'] = datetime.utcnow()
        result = db.shopping_items.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': update_data}
        )
        if result.modified_count > 0:
            logger.info(f"{trans('general_shopping_item_updated', default='Updated shopping item with ID')}: {item_id}", 
                       extra={'session_id': 'no-session-id'})
            return True
        logger.info(f"{trans('general_shopping_item_no_change', default='No changes made to shopping item with ID')}: {item_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except WriteError as e:
        logger.error(f"{trans('general_shopping_item_update_error', default='Error updating shopping item with ID')} {item_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"{trans('general_shopping_item_update_error', default='Error updating shopping item with ID')} {item_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def to_dict_budget(record):
    """Convert budget record to dictionary."""
    if not record:
        return {'surplus_deficit': None, 'savings_goal': None}
    return {
        'id': str(record.get('_id', '')),
        'income': record.get('income', 0),
        'fixed_expenses': record.get('fixed_expenses', 0),
        'variable_expenses': record.get('variable_expenses', 0),
        'savings_goal': record.get('savings_goal', 0),
        'surplus_deficit': record.get('surplus_deficit', 0),
        'housing': record.get('housing', 0),
        'food': record.get('food', 0),
        'transport': record.get('transport', 0),
        'dependents': record.get('dependents', 0),
        'miscellaneous': record.get('miscellaneous', 0),
        'others': record.get('others', 0),
        'custom_categories': record.get('custom_categories', []),
        'created_at': record.get('created_at')
    }

def to_dict_bill(record):
    """Convert bill record to dictionary."""
    if not record:
        return {'bill_name': None, 'amount': None}
    return {
        'id': str(record.get('_id', '')),
        'user_id': record.get('user_id', ''),
        'bill_name': record.get('bill_name', ''),
        'amount': record.get('amount', 0),
        'due_date': record.get('due_date'),
        'frequency': record.get('frequency', ''),
        'category': record.get('category', ''),
        'status': record.get('status', ''),
        'send_notifications': record.get('send_notifications', False),
        'send_email': record.get('send_email', False),
        'send_sms': record.get('send_sms', False),
        'send_whatsapp': record.get('send_whatsapp', False),
        'reminder_days': record.get('reminder_days', None),
        'user_email': record.get('user_email', ''),
        'user_phone': record.get('user_phone', ''),
        'first_name': record.get('first_name', '')
    }

def to_dict_bill_reminder(record):
    """Convert bill reminder record to dictionary."""
    if not record:
        return {'notification_id': None, 'type': None}
    return {
        'id': str(record.get('_id', '')),
        'user_id': record.get('user_id', ''),
        'notification_id': record.get('notification_id', ''),
        'type': record.get('type', ''),
        'message': record.get('message', ''),
        'sent_at': record.get('sent_at'),
        'read_status': record.get('read_status', False)
    }

@lru_cache(maxsize=128)
def get_shopping_lists(db, filter_kwargs):
    """
    Retrieve shopping list records based on filter criteria.
    
    Args:
        db: MongoDB database instance
        filter_kwargs: Dictionary of filter criteria
    
    Returns:
        list: List of normalized shopping list records
    """
    try:
        return [normalize_shopping_list(record) for record in db.shopping_lists.find(filter_kwargs).sort('updated_at', DESCENDING)]
    except Exception as e:
        logger.error(f"{trans('general_shopping_lists_fetch_error', default='Error getting shopping lists')}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def create_shopping_list(db, list_data):
    """
    Create a new shopping list in the shopping_lists collection.
    
    Args:
        db: MongoDB database instance
        list_data: Dictionary containing shopping list information
    
    Returns:
        str: ID of the created shopping list
    """
    try:
        required_fields = ['user_id', 'name', 'budget', 'created_at', 'updated_at', 'total_spent', 'status']
        if not all(field in list_data for field in required_fields):
            raise ValueError(trans('general_missing_shopping_list_fields', default='Missing required shopping list fields'))
        if 'session_id' in list_data and list_data['session_id']:
            list_data['session_id'] = str(list_data['session_id'])  # Ensure session_id is a string if provided
        list_data['_id'] = ObjectId()
        list_data['collaborators'] = list_data.get('collaborators', [])
        result = db.shopping_lists.insert_one(list_data)
        logger.info(f"{trans('general_shopping_list_created', default='Created shopping list with ID')}: {result.inserted_id}", 
                   extra={'session_id': list_data.get('session_id', 'no-session-id')})
        get_shopping_lists.cache_clear()
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"{trans('general_shopping_list_creation_error', default='Error creating shopping list')}: {str(e)}", 
                     exc_info=True, extra={'session_id': list_data.get('session_id', 'no-session-id')})
        raise
    except Exception as e:
        logger.error(f"{trans('general_shopping_list_creation_error', default='Error creating shopping list')}: {str(e)}", 
                     exc_info=True, extra={'session_id': list_data.get('session_id', 'no-session-id')})
        raise

def normalize_shopping_list(record):
    """
    Normalize a shopping list record to ensure consistent structure.
    
    Args:
        record: Raw shopping list document from MongoDB
    
    Returns:
        dict: Normalized shopping list dictionary
    """
    return {
        'id': str(record.get('_id', '')),
        'name': record.get('name', ''),
        'user_id': record.get('user_id', None),
        'session_id': str(record.get('session_id', '')) if record.get('session_id') else None,  # Ensure session_id is a string if present
        'budget': float(record.get('budget', 0.0)),
        'created_at': record.get('created_at', datetime.utcnow()),
        'updated_at': record.get('updated_at', datetime.utcnow()),
        'collaborators': record.get('collaborators', []),
        'total_spent': float(record.get('total_spent', 0.0)),
        'status': record.get('status', 'active')
    }

def update_shopping_list(db, list_id, update_data):
    """
    Update a shopping list in the shopping_lists collection.
    
    Args:
        db: MongoDB database instance
        list_id: The ID of the shopping list to update
        update_data: Dictionary containing fields to update
    
    Returns:
        bool: True if updated, False if not found or no changes made
    """
    try:
        update_data['updated_at'] = datetime.utcnow()
        result = db.shopping_lists.update_one(
            {'_id': ObjectId(list_id)},
            {'$set': update_data}
        )
        if result.modified_count > 0:
            logger.info(f"{trans('general_shopping_list_updated', default='Updated shopping list with ID')}: {list_id}", 
                       extra={'session_id': 'no-session-id'})
            get_shopping_lists.cache_clear()
            return True
        logger.info(f"{trans('general_shopping_list_no_change', default='No changes made to shopping list with ID')}: {list_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except WriteError as e:
        logger.error(f"{trans('general_shopping_list_update_error', default='Error updating shopping list with ID')} {list_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"{trans('general_shopping_list_update_error', default='Error updating shopping list with ID')} {list_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def update_user_balance(db, user_id, amount):
    """
    Update a user's ficore_credit_balance atomically.
    
    Args:
        db: MongoDB database instance
        user_id: The ID of the user to update
        amount: The amount to add to the balance (can be positive or negative)
    
    Returns:
        bool: True if updated, False otherwise
    """
    try:
        result = db.users.update_one(
            {'user_id': user_id},
            {'$inc': {'ficore_credit_balance': amount}}
        )
        if result.modified_count > 0:
            logger.info(f"Updated user {user_id} ficore_credit_balance by {amount}", 
                        extra={'session_id': 'no-session-id'})
            return True
        return False
    except WriteError as e:
        logger.error(f"Error updating user balance for {user_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"Error updating user balance for {user_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def get_ficore_credit_transactions(db, filter_kwargs):
    """
    Retrieve ficore credit transactions based on filter criteria.
    
    Args:
        db: MongoDB database instance
        filter_kwargs: Dictionary of filter criteria
    
    Returns:
        list: List of transaction records
    """
    try:
        return list(db.ficore_credit_transactions.find(filter_kwargs).sort('created_at', DESCENDING))
    except Exception as e:
        logger.error(f"Error getting ficore credit transactions: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def to_dict_shopping_list(record):
    """Convert shopping list record to dictionary."""
    if not record:
        return {'name': None, 'budget': None}
    return {
        'id': str(record.get('_id', '')),
        'name': record.get('name', ''),
        'user_id': record.get('user_id', ''),
        'session_id': str(record.get('session_id', '')),  # Ensure session_id is a string
        'budget': record.get('budget', 0.0),
        'created_at': record.get('created_at'),
        'updated_at': record.get('updated_at'),
        'collaborators': record.get('collaborators', []),
        'total_spent': record.get('total_spent', 0.0),
        'status': record.get('status', '')
    }

def delete_shopping_list(db, list_id, user_id=None, email=None):
    """
    Delete a shopping list and its associated items from the shopping_lists and shopping_items collections.
    
    Args:
        db: MongoDB database instance
        list_id: The ID of the shopping list to delete
        user_id: Optional user ID for ownership check
        email: Optional email for ownership check
    
    Returns:
        bool: True if deleted, False if not found or no changes made
    """
    try:
        filter_criteria = {'_id': ObjectId(list_id)}
        if user_id and email:
            filter_criteria.update({'user_id': user_id, 'email': email.lower()})
        
        with db.client.start_session() as session:
            with session.start_transaction():
                list_result = db.shopping_lists.delete_one(filter_criteria, session=session)
                if list_result.deleted_count == 0:
                    logger.info(f"No shopping list found with ID {list_id} for deletion", 
                               extra={'session_id': 'no-session-id'})
                    return False
                
                items_result = db.shopping_items.delete_many({'list_id': str(list_id)}, session=session)
                logger.info(f"Deleted shopping list ID {list_id} and {items_result.deleted_count} associated items", 
                           extra={'session_id': 'no-session-id'})
                
                get_shopping_lists.cache_clear()
                return True
    except WriteError as e:
        logger.error(f"Error deleting shopping list ID {list_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"Error deleting shopping list ID {list_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def create_shopping_items_bulk(db, items_data):
    """
    Create multiple shopping items in the shopping_items collection in a single operation.
    
    Args:
        db: MongoDB database instance
        items_data: List of dictionaries containing shopping item information
    
    Returns:
        list: List of IDs of the created shopping items
    """
    try:
        required_fields = ['list_id', 'name', 'quantity', 'price', 'category', 'status', 'created_at', 'updated_at', 'session_id']
        for item in items_data:
            if not all(field in item for field in required_fields):
                raise ValueError(f"Missing required fields in item: {item}")
            item['session_id'] = str(item['session_id'])  # Ensure session_id is a string
            item['unit'] = item.get('unit', 'piece')
        
        result = db.shopping_items.insert_many(items_data)
        logger.info(f"Created {len(result.inserted_ids)} shopping items", 
                   extra={'session_id': items_data[0].get('session_id', 'no-session-id') if items_data else 'no-session-id'})
        return [str(id) for id in result.inserted_ids]
    except WriteError as e:
        logger.error(f"Error creating bulk shopping items: {str(e)}", 
                    exc_info=True, extra={'session_id': items_data[0].get('session_id', 'no-session-id') if items_data else 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"Error creating bulk shopping items: {str(e)}", 
                    exc_info=True, extra={'session_id': items_data[0].get('session_id', 'no-session-id') if items_data else 'no-session-id'})
        raise

def update_budget(db, budget_id, update_data):
    """
    Update a budget record in the budgets collection.
    
    Args:
        db: MongoDB database instance
        budget_id: The ID of the budget record to update
        update_data: Dictionary containing fields to update
    
    Returns:
        bool: True if updated, False if not found or no changes made
    """
    try:
        result = db.budgets.update_one(
            {'_id': ObjectId(budget_id)},
            {'$set': update_data}
        )
        if result.modified_count > 0:
            logger.info(f"{trans('general_budget_updated', default='Updated budget record with ID')}: {budget_id}", 
                       extra={'session_id': 'no-session-id'})
            return True
        logger.info(f"{trans('general_budget_no_change', default='No changes made to budget record with ID')}: {budget_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except WriteError as e:
        logger.error(f"{trans('general_budget_update_error', default='Error updating budget record with ID')} {budget_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"{trans('general_budget_update_error', default='Error updating budget record with ID')} {budget_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def update_bill(db, bill_id, update_data):
    """
    Update a bill record in the bills collection.
    
    Args:
        db: MongoDB database instance
        bill_id: The ID of the bill record to update
        update_data: Dictionary containing fields to update
    
    Returns:
        bool: True if updated, False if not found or no changes made
    """
    try:
        result = db.bills.update_one(
            {'_id': ObjectId(bill_id)},
            {'$set': update_data}
        )
        if result.modified_count > 0:
            logger.info(f"{trans('general_bill_updated', default='Updated bill record with ID')}: {bill_id}", 
                       extra={'session_id': 'no-session-id'})
            return True
        logger.info(f"{trans('general_bill_no_change', default='No changes made to bill record with ID')}: {bill_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except WriteError as e:
        logger.error(f"{trans('general_bill_update_error', default='Error updating bill record with ID')} {bill_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"{trans('general_bill_update_error', default='Error updating bill record with ID')} {bill_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def update_bill_reminder(db, reminder_id, update_data):
    """
    Update a bill reminder in the bill_reminders collection.
    
    Args:
        db: MongoDB database instance
        reminder_id: The ID of the bill reminder to update
        update_data: Dictionary containing fields to update
    
    Returns:
        bool: True if updated, False if not found or no changes made
    """
    try:
        result = db.bill_reminders.update_one(
            {'_id': ObjectId(reminder_id)},
            {'$set': update_data}
        )
        if result.modified_count > 0:
            logger.info(f"{trans('general_bill_reminder_updated', default='Updated bill reminder with ID')}: {reminder_id}", 
                       extra={'session_id': 'no-session-id'})
            return True
        logger.info(f"{trans('general_bill_reminder_no_change', default='No changes made to bill reminder with ID')}: {reminder_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except WriteError as e:
        logger.error(f"{trans('general_bill_reminder_update_error', default='Error updating bill reminder with ID')} {reminder_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"{trans('general_bill_reminder_update_error', default='Error updating bill reminder with ID')} {reminder_id}: {str(e)}", 
                    exc_info=True, extra={'session_id': 'no-session-id'})
        raise

@lru_cache(maxsize=128)
def get_user(db, user_id):
    """
    Get user by ID with caching.
    
    Args:
        db: MongoDB database instance
        user_id: User ID
    
    Returns:
        User object or None
    """
    try:
        user_doc = db.users.find_one({'_id': user_id})
        if user_doc:
            class UserObj:
                def __init__(self, doc):
                    for key, value in doc.items():
                        setattr(self, key, value)
                    self.ficore_credit_balance = int(doc.get('ficore_credit_balance', 0))
            return UserObj(user_doc)
        return None
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {str(e)}")
        return None

@lru_cache(maxsize=128)
def get_user_by_email(db, email):
    """
    Get user by email with caching.
    
    Args:
        db: MongoDB database instance
        email: User email
    
    Returns:
        User object or None
    """
    try:
        user_doc = db.users.find_one({'email': email.lower()})
        if user_doc:
            class UserObj:
                def __init__(self, doc):
                    for key, value in doc.items():
                        setattr(self, key, value)
                    self.ficore_credit_balance = int(doc.get('ficore_credit_balance', 0))
            return UserObj(user_doc)
        return None
    except Exception as e:
        logger.error(f"Error getting user by email {email}: {str(e)}")
        return None

def create_user(db, user_data):
    """
    Create a new user in the database.
    
    Args:
        db: MongoDB database instance
        user_data: Dictionary containing user information
    
    Returns:
        str: ID of the created user
    """
    try:
        if 'password' in user_data:
            user_data['password_hash'] = generate_password_hash(user_data.pop('password'))
        
        user_data.setdefault('created_at', datetime.utcnow())
        user_data.setdefault('ficore_credit_balance', 10)
        user_data.setdefault('role', 'personal')
        user_data.setdefault('is_admin', False)
        user_data.setdefault('setup_complete', False)
        
        result = db.users.insert_one(user_data)
        logger.info(f"Created user with ID: {result.inserted_id}")
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"Error creating user: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        raise

def create_credit_request(db, request_data):
    """
    Create a new credit request.
    
    Args:
        db: MongoDB database instance
        request_data: Dictionary containing request information
    
    Returns:
        str: ID of the created request
    """
    try:
        result = db.credit_requests.insert_one(request_data)
        logger.info(f"Created credit request with ID: {result.inserted_id}")
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"Error creating credit request: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error creating credit request: {str(e)}")
        raise

def update_credit_request(db, request_id, update_data):
    """
    Update a credit request.
    
    Args:
        db: MongoDB database instance
        request_id: Request ID
        update_data: Dictionary containing fields to update
    
    Returns:
        bool: True if updated, False otherwise
    """
    try:
        update_data['updated_at'] = datetime.utcnow()
        result = db.credit_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': update_data}
        )
        return result.modified_count > 0
    except WriteError as e:
        logger.error(f"Error updating credit request {request_id}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error updating credit request {request_id}: {str(e)}")
        return False

def get_credit_requests(db, query):
    """
    Get credit requests based on query.
    
    Args:
        db: MongoDB database instance
        query: MongoDB query
    
    Returns:
        list: List of credit requests
    """
    try:
        return list(db.credit_requests.find(query).sort('created_at', -1))
    except Exception as e:
        logger.error(f"Error getting credit requests: {str(e)}")
        return []

def to_dict_credit_request(record):
    """Convert credit request record to dictionary."""
    if not record:
        return {}
    return {
        '_id': str(record.get('_id', '')),
        'user_id': record.get('user_id', ''),
        'amount': record.get('amount', 0),
        'payment_method': record.get('payment_method', ''),
        'receipt_file_id': str(record.get('receipt_file_id', '')) if record.get('receipt_file_id') else None,
        'status': record.get('status', ''),
        'created_at': record.get('created_at'),
        'updated_at': record.get('updated_at'),
        'admin_id': record.get('admin_id')
    }

def get_ficore_credit_transactions(db, query):
    """
    Get Ficore Credit transactions based on query.
    
    Args:
        db: MongoDB database instance
        query: MongoDB query
    
    Returns:
        list: List of transactions
    """
    try:
        return list(db.ficore_credit_transactions.find(query).sort('date', -1))
    except Exception as e:
        logger.error(f"Error getting Ficore Credit transactions: {str(e)}")
        return []

def to_dict_ficore_credit_transaction(record):
    """Convert Ficore Credit transaction record to dictionary."""
    if not record:
        return {}
    return {
        '_id': str(record.get('_id', '')),
        'user_id': record.get('user_id', ''),
        'amount': record.get('amount', 0),
        'type': record.get('type', ''),
        'ref': record.get('ref', ''),
        'payment_method': record.get('payment_method'),
        'facilitated_by_agent': record.get('facilitated_by_agent'),
        'date': record.get('date')
    }

def create_feedback(db, feedback_data):
    """
    Create a new feedback entry.
    
    Args:
        db: MongoDB database instance
        feedback_data: Dictionary containing feedback information
    
    Returns:
        str: ID of the created feedback
    """
    try:
        result = db.feedback.insert_one(feedback_data)
        logger.info(f"Created feedback with ID: {result.inserted_id}")
        return str(result.inserted_id)
    except WriteError as e:
        logger.error(f"Error creating feedback: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error creating feedback: {str(e)}")
        raise

def log_tool_usage(tool_name, db, user_id=None, session_id=None, action=None):
    """
    Log tool usage to the database.
    
    Args:
        tool_name: Name of the tool
        db: MongoDB database instance
        user_id: User ID (optional)
        session_id: Session ID (optional)
        action: Action performed (optional)
    """
    try:
        log_entry = {
            'tool_name': tool_name,
            'user_id': user_id,
            'session_id': str(session_id) if session_id else 'no-session-id',  # Ensure session_id is a string
            'action': action,
            'timestamp': datetime.utcnow()
        }
        db.tool_usage.insert_one(log_entry)
        logger.info(f"Logged tool usage: {tool_name} by user {user_id}", extra={'session_id': log_entry['session_id']})
    except WriteError as e:
        logger.error(f"Error logging tool usage: {str(e)}", extra={'session_id': session_id or 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"Error logging tool usage: {str(e)}", extra={'session_id': session_id or 'no-session-id'})
        raise

def create_shopping_items_bulk(db, items_data):
    """
    Create multiple shopping items in bulk.
    
    Args:
        db: MongoDB database instance
        items_data: List of dictionaries containing shopping item information
    
    Returns:
        list: List of IDs of the created shopping items
    """
    try:
        if not items_data:
            return []
        
        # Validate all items have required fields
        required_fields = ['user_id', 'list_id', 'name', 'quantity', 'price', 'category', 'status', 'created_at', 'updated_at']
        for item_data in items_data:
            if not all(field in item_data for field in required_fields):
                raise ValueError(trans('general_missing_shopping_item_fields', default='Missing required shopping item fields'))
            item_data['unit'] = item_data.get('unit', 'piece')
            if 'session_id' in item_data and item_data['session_id']:
                item_data['session_id'] = str(item_data['session_id'])  # Ensure session_id is a string if provided
        
        result = db.shopping_items.insert_many(items_data)
        logger.info(f"{trans('general_shopping_items_created_bulk', default='Created shopping items in bulk')}: {len(result.inserted_ids)}", 
                   extra={'session_id': items_data[0].get('session_id', 'no-session-id') if items_data else 'no-session-id'})
        return [str(item_id) for item_id in result.inserted_ids]
    except WriteError as e:
        logger.error(f"{trans('general_shopping_items_bulk_creation_error', default='Error creating shopping items in bulk')}: {str(e)}", 
                     exc_info=True, extra={'session_id': items_data[0].get('session_id', 'no-session-id') if items_data else 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"{trans('general_shopping_items_bulk_creation_error', default='Error creating shopping items in bulk')}: {str(e)}", 
                     exc_info=True, extra={'session_id': items_data[0].get('session_id', 'no-session-id') if items_data else 'no-session-id'})
        raise

def normalize_shopping_list(record):
    """
    Normalize shopping list record to ensure consistent data structure.
    
    Args:
        record: Raw shopping list record from database
    
    Returns:
        dict: Normalized shopping list record
    """
    if not record:
        return {}
    
    return {
        'id': str(record.get('_id', '')),
        'name': record.get('name', ''),
        'user_id': record.get('user_id', ''),
        'session_id': record.get('session_id', ''),
        'budget': float(record.get('budget', 0.0)),
        'total_spent': float(record.get('total_spent', 0.0)),
        'status': record.get('status', 'active'),
        'collaborators': record.get('collaborators', []),
        'created_at': record.get('created_at'),
        'updated_at': record.get('updated_at')
    }

def update_shopping_list(db, list_id, update_data):
    """
    Update a shopping list in the shopping_lists collection.
    
    Args:
        db: MongoDB database instance
        list_id: The ID of the shopping list to update
        update_data: Dictionary containing fields to update
    
    Returns:
        bool: True if updated, False if not found or no changes made
    """
    try:
        update_data['updated_at'] = datetime.utcnow()
        result = db.shopping_lists.update_one(
            {'_id': ObjectId(list_id)},
            {'$set': update_data}
        )
        if result.modified_count > 0:
            logger.info(f"{trans('general_shopping_list_updated', default='Updated shopping list with ID')}: {list_id}", 
                       extra={'session_id': 'no-session-id'})
            get_shopping_lists.cache_clear()  # Clear cache after update
            return True
        logger.info(f"{trans('general_shopping_list_no_change', default='No changes made to shopping list with ID')}: {list_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except WriteError as e:
        logger.error(f"{trans('general_shopping_list_update_error', default='Error updating shopping list with ID')} {list_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise
    except Exception as e:
        logger.error(f"{trans('general_shopping_list_update_error', default='Error updating shopping list with ID')} {list_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def delete_shopping_list(db, list_id):
    """
    Delete a shopping list and all its associated items.
    
    Args:
        db: MongoDB database instance
        list_id: The ID of the shopping list to delete
    
    Returns:
        bool: True if deleted, False if not found
    """
    try:
        # First delete all items associated with the list
        db.shopping_items.delete_many({'list_id': str(list_id)})
        
        # Then delete the list itself
        result = db.shopping_lists.delete_one({'_id': ObjectId(list_id)})
        
        if result.deleted_count > 0:
            logger.info(f"{trans('general_shopping_list_deleted', default='Deleted shopping list with ID')}: {list_id}", 
                       extra={'session_id': 'no-session-id'})
            get_shopping_lists.cache_clear()  # Clear cache after deletion
            return True
        logger.info(f"{trans('general_shopping_list_not_found_delete', default='Shopping list not found for deletion with ID')}: {list_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except Exception as e:
        logger.error(f"{trans('general_shopping_list_delete_error', default='Error deleting shopping list with ID')} {list_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def delete_shopping_item(db, item_id):
    """
    Delete a shopping item from the shopping_items collection.
    
    Args:
        db: MongoDB database instance
        item_id: The ID of the shopping item to delete
    
    Returns:
        bool: True if deleted, False if not found
    """
    try:
        result = db.shopping_items.delete_one({'_id': ObjectId(item_id)})
        if result.deleted_count > 0:
            logger.info(f"{trans('general_shopping_item_deleted', default='Deleted shopping item with ID')}: {item_id}", 
                       extra={'session_id': 'no-session-id'})
            return True
        logger.info(f"{trans('general_shopping_item_not_found_delete', default='Shopping item not found for deletion with ID')}: {item_id}", 
                   extra={'session_id': 'no-session-id'})
        return False
    except Exception as e:
        logger.error(f"{trans('general_shopping_item_delete_error', default='Error deleting shopping item with ID')} {item_id}: {str(e)}", 
                     exc_info=True, extra={'session_id': 'no-session-id'})
        raise

def to_dict_shopping_list(record):
    """Convert shopping list record to dictionary."""
    if not record:
        return {'name': None, 'budget': None}
    return {
        'id': str(record.get('_id', '')),
        'user_id': record.get('user_id', ''),
        'session_id': record.get('session_id', ''),
        'name': record.get('name', ''),
        'budget': record.get('budget', 0.0),
        'total_spent': record.get('total_spent', 0.0),
        'status': record.get('status', 'active'),
        'collaborators': record.get('collaborators', []),
        'created_at': record.get('created_at'),
        'updated_at': record.get('updated_at')
    }
