class Tool:
    def __init__(self, name, description, input_schema, func):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.func = func