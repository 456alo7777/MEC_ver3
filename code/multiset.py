class Multiset:
    def __init__(self):
        self.elements = []
        self.element_counts = {}
        self.min_element = None
        self.max_element = None

    def insert(self, element):
        self.elements.append(element)
        self.element_counts[element] = self.element_counts.get(element, 0) + 1

        if self.min_element is None or element < self.min_element:
            self.min_element = element

        if self.max_element is None or element > self.max_element:
            self.max_element = element

    def remove(self, element):
        if element not in self.elements:
            return

        self.elements.remove(element)
        self.element_counts[element] -= 1

        if self.element_counts[element] == 0:
            del self.element_counts[element]

        if element == self.min_element:
            self.min_element = min(self.elements, default=None)

        if element == self.max_element:
            self.max_element = max(self.elements, default=None)

    def check_exist(self, element):
        return element in self.elements

    def get_min(self):
        return self.min_element

    def get_max(self):
        return self.max_element

    def get_elements(self):
        return self.elements

    def sum_of_largest(self, number_of_elements=1000):
        sorted_elements = sorted(self.elements, reverse=True)
        return sum(sorted_elements[:number_of_elements])
    
    def get_size(self):
        return len(self.elements)